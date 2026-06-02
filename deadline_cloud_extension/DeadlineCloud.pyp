import functools
import glob
import os
import sys


def glob_add_path(base, pattern):
    matches = list(glob.iglob(os.path.join(base, pattern)))
    if matches:
        return os.path.join(base, matches[0])
    return base

if sys.platform in ["win32", "cygwin"]:
    paths = [
        "resource",
        "modules",
        "python",
        "libs",
        "*win64*",
        "dlls"
    ]
    dll_path = functools.reduce(glob_add_path, paths, os.path.dirname(sys.executable))
    # Required due to a longstanding bug in C4D to not include the python dll library path required by many compiled libs
    #   Read more here: https://github.com/danbradham/wheels/issues/4#issuecomment-1772721170
    os.add_dll_directory(dll_path)

root = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(root, 'modules'))

import c4d

# This is the ID generated from Maxon's PluginCafe 
# Plugin ID generator for DeadlineCloudSubmitter.
PLUGIN_ID = 1064358

if sys.platform == "darwin":
    try:
        # This command opens the RS renderview panel at
        # Cinema 4D startup until Maxon fixes the issue
        # of Cinema 4D crashing due to PyQt errors on their end.
        c4d.CallCommand(1038666)
    except Exception as e:
        print(f"Failed to open RS renderview panel: {e}")

class DeadlineCloudRenderCommand(c4d.plugins.CommandData):

    def _import_and_show_submitter(self):
        _diag("_import_and_show_submitter: importing deadline.cinema4d_submitter")
        import deadline.cinema4d_submitter
        _diag("_import_and_show_submitter: calling show_submitter()")
        deadline.cinema4d_submitter.show_submitter()
        _diag("_import_and_show_submitter: show_submitter() returned")

    def _execute_for_mac(self):
        # This variable will be replaced to a path when the installer is running
        C4D_MAC_INSTALLATION_PATH = "C4D_Submitter_Installation_Dir_To_Replace"
        sys.path.append(C4D_MAC_INSTALLATION_PATH)
        try:
            self._import_and_show_submitter()
        finally:
            sys.path.remove(C4D_MAC_INSTALLATION_PATH)

    def Execute(self, doc):
        _diag(f"Execute() entered; sys.platform={sys.platform}")
        try:
            if sys.platform == "darwin":
                self._execute_for_mac()
            else:
                self._import_and_show_submitter()
        except Exception as e:
            import traceback
            _diag(f"Execute() raised: {e!r}\n{traceback.format_exc()}")
            raise
        _diag("Execute() returning True")
        return True


def _diag(msg):
    """Test-only diagnostic logger. C4D's stdout is detached from the
    pytest stdout on Mac, so we write to a known tmp file when
    DEADLINE_CLOUD_AUTO_OPEN_SUBMITTER is set. Cheap to keep — guard
    silences it for normal runs."""
    if os.environ.get("DEADLINE_CLOUD_AUTO_OPEN_SUBMITTER") != "1":
        return
    try:
        with open("/tmp/deadline-c4d-plugin.log", "a") as f:
            f.write(f"{msg}\n")
    except Exception:
        pass


if __name__ == '__main__':

    _diag(f"plugin __main__ entered; sys.platform={sys.platform}")
    try:
        c4d.plugins.RegisterCommandPlugin(
            id=PLUGIN_ID,
            str="AWS Deadline Cloud Submitter",
            info=0,
            help="Submit to AWS Deadline Cloud",
            dat=DeadlineCloudRenderCommand(),
            icon=None
        )
        _diag("RegisterCommandPlugin returned")
    except RuntimeError as e:
        # Cinema 4D raises when the same plugin id is loaded twice. This
        # happens whenever a developer also has an installed copy of the
        # submitter at ~/Library/Preferences/Maxon/.../plugins/. We let
        # the first registration win — CallCommand(PLUGIN_ID) below will
        # still dispatch to the already-registered command.
        if "collides" not in str(e):
            raise
        _diag(f"RegisterCommandPlugin: id already registered, continuing ({e!r})")

def PluginMessage(id, data):
    """C4D lifecycle hook. We use C4DPL_PROGRAM_STARTED — fired once the
    application is fully initialized — to auto-open a scene file and
    the submitter for the integ test.

    On macOS, C4D's binary ignores argv file arguments (it only receives
    files via Apple Events / `open`). The test passes the scene path via
    the DEADLINE_CLOUD_SCENE_PATH env var and we open it here with
    LoadDocument so the submitter sees a real document with a valid path.
    """
    if id == c4d.C4DPL_PROGRAM_STARTED:
        if os.environ.get("DEADLINE_CLOUD_AUTO_OPEN_SUBMITTER") == "1":
            # Patch botocore so the `management.` host-prefix Deadline
            # injects on every API call is stripped. Without this, requests
            # go to http://management.127.0.0.1:<port> and miss the mock.
            # Must be done here (not at module top-level) because
            # C4DPYTHONPATH311 paths aren't on sys.path until C4D finishes
            # initializing.
            try:
                import botocore.awsrequest as _ar
                _orig_urljoin = _ar._urljoin
                def _patched_urljoin(endpoint_url, url_path, host_prefix):
                    return _orig_urljoin(endpoint_url, url_path, None)
                _ar._urljoin = _patched_urljoin
                _diag("botocore host-prefix patch applied")
            except Exception as e:
                _diag(f"botocore host-prefix patch failed: {e!r}")

            scene_path = os.environ.get("DEADLINE_CLOUD_SCENE_PATH", "")
            if scene_path:
                _diag(f"PluginMessage: loading scene {scene_path}")
                try:
                    doc = c4d.documents.LoadDocument(
                        scene_path, c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS
                    )
                    if doc:
                        c4d.documents.InsertBaseDocument(doc)
                        c4d.documents.SetActiveDocument(doc)
                        c4d.EventAdd()
                        _diag("PluginMessage: scene loaded and set as active")
                    else:
                        _diag(f"PluginMessage: LoadDocument returned None for {scene_path}")
                except Exception as e:
                    import traceback
                    _diag(f"PluginMessage: LoadDocument raised: {e!r}\n{traceback.format_exc()}")

            # Verify the active document has a valid path before opening
            # the submitter. LoadDocument + SetActiveDocument above should
            # have done this, but log for diagnostics.
            active = c4d.documents.GetActiveDocument()
            _diag(
                f"PluginMessage: active doc = {active.GetDocumentName() if active else None}, "
                f"path = {active.GetDocumentPath() if active else None}"
            )

            _diag(
                f"PluginMessage(C4DPL_PROGRAM_STARTED): auto-opening submitter "
                f"via CallCommand({PLUGIN_ID})"
            )
            try:
                rc = c4d.CallCommand(PLUGIN_ID)
                _diag(f"CallCommand returned: {rc!r}")
            except Exception as e:
                import traceback
                _diag(f"CallCommand raised: {e!r}\n{traceback.format_exc()}")
    return True
