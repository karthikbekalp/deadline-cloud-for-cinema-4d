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

Where the submitter's AWS calls go depends on the test mode:

* Default: the real Deadline Cloud service, using the machine's ambient
  credentials and default config. The plugin does not touch botocore's endpoint
  or host-prefix handling.
* Offline/mock mode (``DEADLINE_CLOUD_MOCK_MODE=1``): the test points the
  submitter at a local mock backend via ``AWS_ENDPOINT_URL_DEADLINE``. Because
  the Deadline service model injects a ``management.`` host prefix
  (``management.<host>``), this plugin patches ``socket.getaddrinfo`` so any
  ``management.*`` host resolves to ``127.0.0.1`` -- otherwise the prefixed host
  would not resolve to the loopback mock. The patch is gated on the env var, so
  the real-service path is completely unaffected.

The test then drives the resulting Qt dialog with xa11y.
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


def _install_management_host_redirect():
    """Offline-mode only: make botocore's ``management.``-prefixed Deadline host
    resolve to the loopback mock.

    The Deadline service model injects a ``management.`` host prefix onto every
    operation, so a client pointed at ``http://127.0.0.1:<port>`` via
    ``AWS_ENDPOINT_URL_DEADLINE`` actually tries to connect to
    ``management.127.0.0.1`` (and, for a ``localhost`` endpoint,
    ``management.localhost``), which won't resolve to the mock. We patch
    ``socket.getaddrinfo`` so any host starting with ``management.`` resolves to
    ``127.0.0.1``. Gated on ``DEADLINE_CLOUD_MOCK_MODE`` so the real-service path
    is never touched.
    """
    if os.environ.get("DEADLINE_CLOUD_MOCK_MODE") != "1":
        return
    try:
        import socket

        if getattr(socket, "_deadline_mgmt_redirect_installed", False):
            return
        _orig_getaddrinfo = socket.getaddrinfo

        def _patched_getaddrinfo(host, *args, **kwargs):
            if isinstance(host, str) and host.startswith("management."):
                host = "127.0.0.1"
            return _orig_getaddrinfo(host, *args, **kwargs)

        socket.getaddrinfo = _patched_getaddrinfo
        socket._deadline_mgmt_redirect_installed = True
        _diag("management.* -> 127.0.0.1 getaddrinfo redirect installed (mock mode)")
    except Exception as e:
        _diag(f"management host redirect install failed: {e!r}")


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


def _install_api_call_logger():
    """DIAGNOSTIC / DISCOVERY: log every AWS API call the submitter makes.

    Every boto3 client method (deadline, s3, sts, paginated and retried calls
    alike) funnels through ``botocore.client.BaseClient._make_api_call``, so
    wrapping that single method captures the complete, real set of AWS
    operations the Export-bundle flow invokes against the live farm -- including
    anything indirect or paginated that reading the source would miss.

    Two log destinations, both opt-in via env var:

    * ``DEADLINE_CLOUD_API_LOG`` (falls back to ``DEADLINE_CLOUD_DIAG_LOG``):
      one human-readable ``API-CALL <service> <operation> <ms>ms`` line per
      call, with a ``FAILED`` variant so calls that errored are still counted.
    * ``DEADLINE_CLOUD_API_TRACE``: one JSON object per line capturing the
      service, operation, request params, response body (minus the noisy
      ``ResponseMetadata``), elapsed milliseconds, and ok/error -- so a later
      phase can seed the offline mock and the golden bundle from REAL response
      data rather than hand-written guesses.

    Capturing real bodies and timings is what lets the offline mock be grounded
    on observed reality: we replay what the live service actually returned.
    """
    try:
        import json
        import time
        from datetime import datetime
        from botocore.client import BaseClient

        api_log_path = os.environ.get("DEADLINE_CLOUD_API_LOG") or os.environ.get(
            "DEADLINE_CLOUD_DIAG_LOG"
        )
        api_trace_path = os.environ.get("DEADLINE_CLOUD_API_TRACE")

        def _api_log(msg):
            if not api_log_path:
                return
            try:
                with open(api_log_path, "a", encoding="utf-8") as f:
                    f.write(f"{msg}\n")
            except Exception:
                pass

        def _json_default(obj):
            # Deadline/STS responses carry datetimes (createdAt, expiration);
            # serialize them as ISO-8601 so the trace is valid JSON.
            if isinstance(obj, datetime):
                return obj.isoformat()
            return repr(obj)

        def _api_trace(record):
            if not api_trace_path:
                return
            try:
                with open(api_trace_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, default=_json_default) + "\n")
            except Exception:
                pass

        if getattr(BaseClient, "_deadline_api_logger_installed", False):
            return
        original_make_api_call = BaseClient._make_api_call

        def _logging_make_api_call(self, operation_name, api_params):
            service = getattr(getattr(self, "meta", None), "service_model", None)
            service_id = service.endpoint_prefix if service is not None else "unknown"
            start = time.monotonic()
            try:
                result = original_make_api_call(self, operation_name, api_params)
                elapsed_ms = (time.monotonic() - start) * 1000.0
                _api_log(f"API-CALL {service_id} {operation_name} {elapsed_ms:.0f}ms")
                # Drop ResponseMetadata (request ids, headers) -- noise for
                # replay, and varies per call.
                body = (
                    {k: v for k, v in result.items() if k != "ResponseMetadata"}
                    if isinstance(result, dict)
                    else result
                )
                _api_trace(
                    {
                        "service": service_id,
                        "operation": operation_name,
                        "params": api_params,
                        "elapsed_ms": round(elapsed_ms, 1),
                        "ok": True,
                        "response": body,
                    }
                )
                return result
            except Exception as e:
                elapsed_ms = (time.monotonic() - start) * 1000.0
                _api_log(
                    f"API-CALL {service_id} {operation_name} {elapsed_ms:.0f}ms FAILED {e!r}"
                )
                _api_trace(
                    {
                        "service": service_id,
                        "operation": operation_name,
                        "params": api_params,
                        "elapsed_ms": round(elapsed_ms, 1),
                        "ok": False,
                        "error": repr(e),
                    }
                )
                raise

        BaseClient._make_api_call = _logging_make_api_call
        BaseClient._deadline_api_logger_installed = True
        _diag(f"API call logger installed (log -> {api_log_path}, trace -> {api_trace_path})")
    except Exception as e:
        _diag(f"API call logger install failed: {e!r}")


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
        _install_api_call_logger()
        # Must run before the submitter opens so its first API call is already
        # redirected to the loopback mock (no-op unless DEADLINE_CLOUD_MOCK_MODE=1).
        _install_management_host_redirect()

        scene_path = os.environ.get("DEADLINE_CLOUD_SCENE_PATH", "")
        if scene_path:
            _load_active_scene(scene_path)

        _open_submitter()
    return True
