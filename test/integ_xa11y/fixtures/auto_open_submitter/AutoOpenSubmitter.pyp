# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Test-only Cinema 4D plugin that auto-opens the submitter for the xa11y integ test.

This plugin is NEVER shipped to customers. test/integ_xa11y/test_cinema4d.py puts
this directory on ``g_additionalModulePath`` so Cinema 4D loads it alongside the
real, unmodified ``deadline_cloud_extension/DeadlineCloud.pyp``. Keeping the test
hook here (rather than in the shipped plugin) means the test exercises the real
plugin exactly as a customer would, while no test-only code reaches production.

Once the application has finished starting (``C4DPL_PROGRAM_STARTED``) this plugin:

1. Loads the test scene named by ``DEADLINE_CLOUD_SCENE_PATH`` and makes it the
   active document. Cinema 4D ignores argv file arguments on macOS (files only
   arrive via Apple Events), so the scene is passed by env var and opened here,
   giving the submitter a document with a valid path.
2. Opens the real submitter via ``c4d.CallCommand(SUBMITTER_PLUGIN_ID)``, which
   dispatches into the shipped plugin's registered command — the same entry point
   a user hits by clicking ``Extensions > AWS Deadline Cloud Submitter``.

The submitter's AWS calls go to the real Deadline Cloud service using the
machine's ambient credentials and default config; this plugin does not touch
botocore's endpoint or host-prefix handling. The test then drives the resulting
Qt dialog with xa11y.
"""
import os
import traceback

import c4d

# Must match PLUGIN_ID in deadline_cloud_extension/DeadlineCloud.pyp. Duplicated as
# a literal so this test fixture needs no import from the shipped plugin.
SUBMITTER_PLUGIN_ID = 1064358


def _diag(msg):
    """Append a diagnostic line to the file named by ``DEADLINE_CLOUD_DIAG_LOG``.

    Cinema 4D's stdout is detached from pytest's, so the test points this env var
    at a file under its staging dir and reads it back to surface failures. The
    test owns the path, so it is cross-platform; a no-op when the var is unset.
    """
    log_path = os.environ.get("DEADLINE_CLOUD_DIAG_LOG")
    if not log_path:
        return
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{msg}\n")
    except Exception:
        pass


def _install_diag_log_capture():
    """DIAGNOSTIC: surface errors that the submitter dialog swallows.

    on_export_bundle wraps its body in `except Exception: logger.exception(...)`
    and then shows a QMessageBox.critical -- so when get_parameters() blows up
    with "Internal C++ object (QLineEdit) already deleted" (a Qt object-lifetime
    race: a parameter control was deleteLater()'d by an overlapping queue-env
    rebuild_ui while Export was reading it), the traceback only goes to the
    `deadline.client` logger, which lands in C4D's console -- detached from
    pytest. We attach a handler that mirrors that logger into
    DEADLINE_CLOUD_DIAG_LOG (which the test echoes back on teardown), and add a
    sys.excepthook, so the real root cause shows up in the test output.
    """
    try:
        import logging

        log_path = os.environ.get("DEADLINE_CLOUD_DIAG_LOG")
        if log_path:
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setLevel(logging.WARNING)
            handler.setFormatter(
                logging.Formatter("[deadline-logger %(levelname)s %(name)s] %(message)s")
            )
            # Capture only the deadline client logs at WARNING+ (where "Error
            # saving bundle" and the swallowed traceback are emitted). botocore
            # at DEBUG is far too noisy and buries the signal, so we do NOT
            # attach to the root logger here.
            lg = logging.getLogger("deadline")
            lg.setLevel(logging.WARNING)
            lg.addHandler(handler)
        _diag("diag log capture installed (deadline logger WARNING+ -> diag file)")
    except Exception as e:
        _diag(f"diag log capture install failed: {e!r}")

    # Also capture any genuinely-uncaught exceptions on the main thread.
    try:
        import sys

        prev_hook = sys.excepthook

        def _hook(exc_type, exc_value, exc_tb):
            _diag(
                "UNCAUGHT EXCEPTION:\n"
                + "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            )
            prev_hook(exc_type, exc_value, exc_tb)

        sys.excepthook = _hook
    except Exception as e:
        _diag(f"excepthook install failed: {e!r}")


def _load_active_scene(scene_path):
    """Load ``scene_path`` and set it as the active document so the submitter sees
    a real document with a valid path."""
    _diag(f"loading scene {scene_path}")
    try:
        doc = c4d.documents.LoadDocument(
            scene_path, c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS
        )
        if doc:
            c4d.documents.InsertBaseDocument(doc)
            c4d.documents.SetActiveDocument(doc)
            c4d.EventAdd()
            _diag("scene loaded and set as active")
        else:
            _diag(f"LoadDocument returned None for {scene_path}")
    except Exception as e:
        _diag(f"LoadDocument raised: {e!r}\n{traceback.format_exc()}")


def _open_submitter():
    """Dispatch into the real shipped plugin's submitter command."""
    active = c4d.documents.GetActiveDocument()
    _diag(
        f"active doc = {active.GetDocumentName() if active else None}, "
        f"path = {active.GetDocumentPath() if active else None}"
    )
    _diag(f"opening submitter via CallCommand({SUBMITTER_PLUGIN_ID})")
    try:
        rc = c4d.CallCommand(SUBMITTER_PLUGIN_ID)
        _diag(f"CallCommand returned: {rc!r}")
    except Exception as e:
        _diag(f"CallCommand raised: {e!r}\n{traceback.format_exc()}")


def PluginMessage(id, data):
    """Cinema 4D lifecycle hook. We act on C4DPL_PROGRAM_STARTED, fired once the
    application is fully initialized, to drive the submitter for the integ test."""
    if id == c4d.C4DPL_PROGRAM_STARTED:
        _diag("C4DPL_PROGRAM_STARTED: auto-opening submitter for integ test")
        _install_diag_log_capture()

        scene_path = os.environ.get("DEADLINE_CLOUD_SCENE_PATH", "")
        if scene_path:
            _load_active_scene(scene_path)

        _open_submitter()
    return True
