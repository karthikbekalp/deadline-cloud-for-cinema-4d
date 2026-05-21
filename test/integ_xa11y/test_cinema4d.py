# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
import os
import subprocess
import tempfile
import time
from pathlib import Path
from shutil import copy2, rmtree

import pytest
import xa11y

from .utils import (
    assert_all_images_close,
    assert_expected_job_bundle_and_generated_job_bundle_are_equal,
    assert_is_valid_job_bundle,
    assert_openjd_run_with_cinema4d_successful,
    build_cube_scene,
    build_submitter_pythonpath,
    kill_proc,
    log,
    override_job_history_dir,
    resolve_c4d_gui_exe,
    wait_for_bundle,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_PLUGIN_DIR = _REPO_ROOT / "deadline_cloud_extension"
_REAL_PLUGIN_FILE = _REAL_PLUGIN_DIR / "DeadlineCloud.pyp"

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
_SUCCESS_DIALOG_PREFIX = "Cinema4D job submission"
# Both the UIA App for the dialog and the dialog window itself surface
# the same name (the QApplication display name + version), so we reuse
# the same prefix for both.
_DIALOG_APP_PREFIX = _DIALOG_NAME_PREFIX

_C4D_BOOT_TIMEOUT_S = 180.0
_DIALOG_VISIBLE_TIMEOUT_S = 60.0
_BUNDLE_EXPORT_TIMEOUT_S = 60.0
_BUNDLE_ON_DISK_TIMEOUT_S = 30.0


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


@pytest.mark.parametrize("test_name", ["cube"])
def test_integ(
    cinema4d_location: Path,
    test_scenes_folder_location: Path,
    test_name: str,
) -> None:
    """
    Performs integration testing for Cinema 4D rendering, driven through
    the real submitter UI via xa11y.

    This test exercises the full submitter flow:
    1. Builds a test scene with c4dpy
    2. Launches Cinema 4D with the repo plugin and scene loaded
    3. Sends Shift+C + "AWS Deadline Cloud Submitter" + Enter via
       xa11y.input_sim() to launch the submitter via Cinema 4D's
       Commander palette (the menu bar is not exposed to UIA)
    4. Drives the resulting Qt submitter dialog via xa11y locator
       (Export bundle button + success popup)
    5. Copies the exported job bundle into generated_bundle/
    6. Validates the bundle structure (openjd check)
    7. Compares against expected_job_bundle/
    8. Executes the bundle via openjd run with Cinema 4D Commandline
    9. Compares rendered output against expected_job_output/
    10. Cleans up generated files on successful completion

    Args:
        cinema4d_location (Path): Path to the Cinema 4D installation directory
        test_scenes_folder_location (Path): Path to the root directory containing test scenes

    Raises:
        AssertionError: If any validation step fails, including:
            - Cinema 4D failing to launch
            - Submitter dialog not appearing in the UIA tree
            - Export bundle not producing the expected files
            - openjd check reporting a non-success status
            - openjd run failing for any step
    """
    assert _REAL_PLUGIN_FILE.is_file(), f"DeadlineCloud.pyp not found at {_REAL_PLUGIN_FILE}"

    c4dpy_location = cinema4d_location / "c4dpy"
    test_scene_folder_location = test_scenes_folder_location / test_name
    test_scene_script_location = test_scene_folder_location / "scene" / "scene.py"
    job_bundle_generated = test_scene_folder_location / "generated_bundle"
    os.makedirs(job_bundle_generated, exist_ok=True)

    cinema4d_gui_exe = resolve_c4d_gui_exe(cinema4d_location)
    # Save the scene into generated_bundle/ rather than scene/ so that
    # render_data RDATA_PATH = "renders/$prj" (resolved against
    # doc.GetDocumentPath()) lands renders inside generated_bundle/renders/,
    # matching the layout assert_all_images_close expects. Same trick the
    # existing test/integ/ test relies on.
    scene_path = build_cube_scene(
        c4dpy_location, test_scene_script_location, job_bundle_generated
    )

    env = {
        **os.environ,
        # Point C4D at the .pyp checked into this repo. Same env var the
        # InstallBuilder installer sets — C4D scans every dir on this
        # path at startup for plugin files.
        "g_additionalModulePath": (
            str(_REAL_PLUGIN_DIR)
            + os.pathsep
            + os.environ.get("g_additionalModulePath", "")
        ),
        # C4D's bundled Python uses this for extra package resolution.
        # We need the editable submitter source plus the venv site-packages
        # (PySide6 / qtpy / deadline-client all live there).
        "C4DPYTHONPATH311": (
            build_submitter_pythonpath(_REPO_ROOT)
            + os.pathsep
            + os.environ.get("C4DPYTHONPATH311", "")
        ),
    }

    # The submitter exports via create_job_history_bundle_dir, which always
    # writes under <history_dir>/<YYYY-mm>/<bundle-name>/. Point the history
    # at a staging dir, then copy the bundle files flat into generated_bundle/
    # so asserts use the same layout as the existing render integ tests.
    bundle_staging = Path(tempfile.mkdtemp(prefix="c4d-submitter-ui-"))
    log(f"bundle staging dir: {bundle_staging}")
    try:
        with override_job_history_dir(bundle_staging):
            log(f"launching Cinema 4D: {cinema4d_gui_exe} {scene_path}")
            proc = subprocess.Popen(
                [str(cinema4d_gui_exe), str(scene_path)],
                env=env,
            )
            log(f"Cinema 4D launched, pid={proc.pid}")
            try:
                log(f"waiting up to {_C4D_BOOT_TIMEOUT_S:.0f}s for xa11y to attach by pid")
                app = xa11y.App.by_pid(proc.pid, timeout=_C4D_BOOT_TIMEOUT_S)
                log("xa11y attached to Cinema 4D")

                # Cinema 4D's main window does not expose its custom menu
                # bar to UI Automation, and Cinema 4D's top-level menus do
                # not respond to Alt-mnemonics on Windows (its menu bar is
                # custom-drawn). Instead we drive the built-in Commander
                # (Shift+C), a fuzzy command palette that can launch any
                # registered command by name — including our submitter.
                log("settling 5s before sending keyboard input")
                time.sleep(5)

                # Cinema 4D's Commander index can take a few seconds to
                # populate after a cold start, so the first attempt sometimes
                # arrows down on an empty list. Retry the open + type +
                # activate sequence until the dialog UIA app appears.
                dialog_app = None
                for attempt in range(1, 4):
                    log(f"Commander attempt {attempt}/3")

                    # Make sure Cinema 4D has OS focus before we send keys;
                    # otherwise input_sim posts to whatever window the
                    # terminal/IDE last had focused.
                    try:
                        app.as_element().focus()
                    except Exception as e:
                        log(f"focus() failed (non-fatal): {e!r}")

                    input_sim = xa11y.input_sim()
                    log("  Shift+C to open Commander")
                    input_sim.chord("c", held=["Shift"])
                    time.sleep(1.0)

                    log("  typing 'AWS Deadline Cloud Submitter'")
                    input_sim.type_text("AWS Deadline Cloud Submitter")
                    # Wait long enough for Commander to filter results;
                    # the first attempt after a cold start can be slow.
                    time.sleep(3.0)

                    log("  ArrowDown to highlight the first match")
                    input_sim.press("ArrowDown")
                    time.sleep(0.5)

                    log("  pressing Enter to launch")
                    input_sim.press("Enter")
                    time.sleep(1.0)

                    log("  polling App.list() for the dialog")
                    dialog_app = _wait_for_dialog_app(
                        pid=proc.pid,
                        name_prefix=_DIALOG_APP_PREFIX,
                        timeout_s=15.0,
                    )
                    if dialog_app is not None:
                        break
                    log(
                        f"  attempt {attempt}: dialog did not appear, "
                        f"sending Escape and retrying"
                    )
                    # Make sure Commander is dismissed before retrying.
                    try:
                        input_sim.press("Escape")
                    except Exception:
                        pass
                    time.sleep(2.0)
                if dialog_app is None:
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
                    raise AssertionError(
                        "Submitter dialog did not register with UIA "
                        f"(expected app name prefix {_DIALOG_APP_PREFIX!r})"
                    )
                log(f"submitter dialog UIA app: {dialog_app.name!r}")
                # Dump what's inside the dialog app's tree so we can pin
                # the right selector on first run.
                try:
                    log("dialog app tree (depth=8):")
                    print(dialog_app.dump(max_depth=8))
                except Exception as e:
                    log(f"dialog_app.dump() failed: {e!r}")

                log(f"waiting for dialog: {_DIALOG_NAME_PREFIX!r}")
                # UIA exposes Qt's top-level dialog with role=dialog and the
                # QApplication display name as its accessible name (which is
                # what UIA surfaces, not Qt's windowTitle).
                dialog = dialog_app.locator(
                    f"dialog[name^='{_DIALOG_NAME_PREFIX}']"
                )
                try:
                    dialog.wait_visible(timeout=_DIALOG_VISIBLE_TIMEOUT_S)
                except Exception:
                    log("dialog window selector failed; final dialog app tree:")
                    try:
                        print(dialog_app.dump())
                    except Exception:
                        pass
                    raise
                log("submitter dialog visible")

                # The dialog renders "Loading Queue Environments..." as a
                # placeholder while the auth probe + queue-env fetch runs.
                # If we click Export bundle before that resolves, the
                # callback fires with empty queue parameters and the export
                # path inside the submitter throws. Wait for the loading
                # text to disappear before proceeding.
                log("waiting for queue environment loading to finish")
                loading = dialog_app.locator(
                    "static_text[name^='Loading Queue Environments']"
                )
                try:
                    loading.wait_hidden(timeout=_DIALOG_VISIBLE_TIMEOUT_S)
                    log("queue environment loading finished")
                except Exception as e:
                    log(f"loading-text wait failed (non-fatal): {e!r}")

                log(f"waiting for button: {_EXPORT_BUTTON_NAME!r}")
                # xa11y's Locator chaining method is `descendant`, not
                # `locator` — Locator has no .locator() (only App does).
                export_btn = dialog.descendant(
                    f"button[name='{_EXPORT_BUTTON_NAME}']"
                )
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

                # The submitter pops a QMessageBox.information on success
                # before closing the dialog. Dismiss it so C4D returns to idle.
                # Same UIA app as the dialog itself (same Qt process).
                # The success popup may surface as either a dialog or a window
                # depending on Qt's Win UIA mapping; match either via comma
                # alternation in the selector.
                log(f"waiting for success popup: {_SUCCESS_DIALOG_PREFIX!r}")
                success = dialog_app.locator(
                    f"dialog[name^='{_SUCCESS_DIALOG_PREFIX}'], "
                    f"window[name^='{_SUCCESS_DIALOG_PREFIX}']"
                )
                success.wait_visible(timeout=_BUNDLE_EXPORT_TIMEOUT_S)
                log("dismissing success popup (OK)")
                success.descendant("button[name='OK']").press()

                staged_bundle = wait_for_bundle(
                    bundle_staging, timeout_s=_BUNDLE_ON_DISK_TIMEOUT_S
                )
                # Copy bundle files flat into generated_bundle/.
                log(f"copying bundle files {staged_bundle} -> {job_bundle_generated}")
                for src in staged_bundle.iterdir():
                    if src.is_file():
                        copy2(src, job_bundle_generated / src.name)
                        log(f"  copied {src.name}")
            finally:
                kill_proc(proc)
    finally:
        rmtree(bundle_staging, ignore_errors=True)
        log(f"removed staging dir: {bundle_staging}")

    log("running openjd check on the exported bundle")
    assert_is_valid_job_bundle(job_bundle_generated / "template.yaml")

    log("comparing generated bundle against expected_job_bundle/")
    expected_job_bundle = test_scene_folder_location / "expected_job_bundle"
    assert_expected_job_bundle_and_generated_job_bundle_are_equal(
        expected_job_bundle, job_bundle_generated
    )

    log("running openjd run with Cinema 4D Commandline for each step")
    assert_openjd_run_with_cinema4d_successful(
        cinema4d_location,
        job_bundle_generated / "template.yaml",
        job_bundle_generated / "parameter_values.yaml",
    )

    log("comparing rendered output against expected_job_output/")
    expected_job_output = test_scene_folder_location / "expected_job_output"
    assert_all_images_close(
        expected_job_output / "renders",
        job_bundle_generated / "renders",
    )

    # Clean up if the test was successful
    rmtree(job_bundle_generated, ignore_errors=True)
