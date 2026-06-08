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
    override_job_history_dir,
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
_SUCCESS_DIALOG_PREFIX = "Cinema4D job submission"
# Both the UIA App for the dialog and the dialog window itself surface
# the same name (the QApplication display name + version), so we reuse
# the same prefix for both.
_DIALOG_APP_PREFIX = _DIALOG_NAME_PREFIX

_C4D_BOOT_TIMEOUT_S = 180.0
_DIALOG_VISIBLE_TIMEOUT_S = 60.0
_BUNDLE_EXPORT_TIMEOUT_S = 60.0
_BUNDLE_ON_DISK_TIMEOUT_S = 30.0


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
    mock_deadline_farm: dict,
    scene_path: Path,
    plugin_diag_log: Path,
) -> dict:
    """Build the environment for the Cinema 4D subprocess.

    Mock farm env vars point AWS clients at our in-process HTTP servers.
    The shim dir contains a sitecustomize.py that strips the `management.`
    host prefix botocore injects on every deadline: call.
    """
    mock_env = mock_deadline_farm["env"]
    shim_dir = mock_deadline_farm["shim_dir"]

    return {
        **os.environ,
        **mock_env,
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
        # (PySide6 / qtpy / deadline-client all live there) and the shim
        # dir so sitecustomize patches botocore on interpreter start.
        "C4DPYTHONPATH311": _prepend(
            shim_dir,
            _prepend(
                build_submitter_pythonpath(_REPO_ROOT),
                os.environ.get("C4DPYTHONPATH311", ""),
                os.pathsep,
            ),
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


def _launch_cinema4d(
    cinema4d_gui_exe: Path, scene_path: Path, env: dict
) -> subprocess.Popen:
    """Launch Cinema 4D with the submitter + sidecar plugins.

    On macOS we don't pass the scene on argv (the sidecar loads it via
    DEADLINE_CLOUD_SCENE_PATH); on Windows we pass it on argv too.
    """
    if sys.platform == "darwin":
        log(f"launching Cinema 4D (mac): {cinema4d_gui_exe}")
        proc = subprocess.Popen(
            [str(cinema4d_gui_exe)],
            env=env,
        )
    else:
        log(f"launching Cinema 4D: {cinema4d_gui_exe} {scene_path}")
        proc = subprocess.Popen(
            [str(cinema4d_gui_exe), str(scene_path)],
            env=env,
        )
    log(f"Cinema 4D launched, pid={proc.pid}")
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
        f"dialog[name^='{_DIALOG_NAME_PREFIX}'], "
        f"window[name^='{_DIALOG_NAME_PREFIX}']"
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
    """Wait for queue environment loading to finish. Non-fatal if it times
    out — Export bundle may still be clickable."""
    log("waiting for queue environment loading to finish")
    loading = dialog_app.locator("static_text[name^='Loading Queue Environments']")
    try:
        loading.wait_hidden(timeout=_DIALOG_VISIBLE_TIMEOUT_S)
        log("queue environment loading finished")
    except Exception as e:
        log(f"loading-text wait failed (non-fatal): {e!r}")


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


def _dismiss_success_popup(dialog_app) -> None:
    """Dismiss the success popup if we can find it, but don't fail if we
    can't — the bundle is already on disk by the time we get here.

    Matching the QMessageBox success popup's AX name is unreliable across
    platforms (on macOS it surfaces differently than on Windows UIA), so the
    bundle-on-disk check is the real source of truth for export success.
    """
    log(f"looking for success popup: {_SUCCESS_DIALOG_PREFIX!r}")
    try:
        success = dialog_app.locator(
            f"dialog[name^='{_SUCCESS_DIALOG_PREFIX}'], "
            f"window[name^='{_SUCCESS_DIALOG_PREFIX}'], "
            f"sheet[name^='{_SUCCESS_DIALOG_PREFIX}']"
        )
        success.wait_visible(timeout=5.0)
        log("dismissing success popup (OK)")
        success.descendant("button[name='OK']").press()
    except Exception:
        log("success popup not found (non-fatal, bundle already exported)")


def _copy_bundle_files(staged_bundle: Path, dest: Path) -> None:
    """Copy the exported bundle files flat into `dest`."""
    log(f"copying bundle files {staged_bundle} -> {dest}")
    for src in staged_bundle.iterdir():
        if src.is_file():
            copy2(src, dest / src.name)
            log(f"  copied {src.name}")


def _drive_submitter_ui(proc: subprocess.Popen, bundle_staging: Path) -> Path:
    """Drive the running submitter dialog via xa11y and return the staged
    bundle directory once it lands on disk.

    Waits for the dialog, lets queue environments finish loading, presses
    Export bundle, then waits for the bundle to appear on disk before
    dismissing the success popup.
    """
    dialog_app = _resolve_dialog_app(proc)
    dialog = _wait_for_submitter_dialog(dialog_app)
    _wait_for_queue_environment_loading(dialog_app)
    _press_export_bundle(dialog, dialog_app)

    # Wait for the bundle to land on disk. This is the source of truth for
    # export success — more reliable than matching the QMessageBox success
    # popup's AX name across platforms.
    staged_bundle = wait_for_bundle(bundle_staging, timeout_s=_BUNDLE_EXPORT_TIMEOUT_S)

    _dismiss_success_popup(dialog_app)
    return staged_bundle


def _export_job_bundle_via_submitter(
    cinema4d_location: Path,
    scene_path: Path,
    mock_deadline_farm: dict,
    job_bundle_generated: Path,
) -> None:
    """Launch Cinema 4D, drive the real submitter UI to export a job bundle,
    and copy the bundle files flat into `job_bundle_generated`.

    The submitter exports via create_job_history_bundle_dir, which always
    writes under <history_dir>/<YYYY-mm>/<bundle-name>/. We point the history
    at a staging dir, then copy the bundle files flat into generated_bundle/
    so asserts use the same layout as the existing render integ tests.

    Owns all cleanup: the C4D subprocess is always killed and its diagnostic
    log echoed before the staging dir is removed, even on failure.
    """
    cinema4d_gui_exe = resolve_c4d_exe(cinema4d_location, "Cinema 4D")

    bundle_staging = Path(tempfile.mkdtemp(prefix="c4d-submitter-ui-"))
    plugin_diag_log = bundle_staging / "plugin-diag.log"
    log(f"bundle staging dir: {bundle_staging}")
    try:
        env = _build_launch_env(mock_deadline_farm, scene_path, plugin_diag_log)
        with override_job_history_dir(bundle_staging):
            proc = _launch_cinema4d(cinema4d_gui_exe, scene_path, env)
            try:
                staged_bundle = _drive_submitter_ui(proc, bundle_staging)
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
    mock_deadline_farm: dict,
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
        mock_deadline_farm=mock_deadline_farm,
        job_bundle_generated=job_bundle_generated,
    )

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
