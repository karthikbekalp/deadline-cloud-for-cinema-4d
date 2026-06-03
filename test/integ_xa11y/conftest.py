# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# This conftest mirrors test/integ/conftest.py. Once the xa11y-driven test
# replaces the existing rendering integ tests, this folder will be renamed
# to test/integ/ and the two files will be merged.

import pytest
import os
import site
import sys
import tempfile
import textwrap
from typing import Iterator

from pathlib import Path

from .mock_deadline_backend import (
    MockDeadlineFarm,
    start_deadline_server,
    start_sts_server,
)

# Default install paths per version and platform.
# Order matters: when scanning for an installed C4D without C4D_LOCATION /
# C4D_VERSION set, the first match wins. Newest version first so dev boxes
# with both installed get 2026.
_C4D_DEFAULT_PATHS = {
    "2026": {
        "win32": Path(r"C:\Program Files\Maxon Cinema 4D 2026"),
        "darwin": Path("/Applications/Maxon Cinema 4D 2026"),
        "linux": Path("/opt/maxon/cinema4d-2026"),
    },
    "2025": {
        "win32": Path(r"C:\Program Files\Maxon Cinema 4D 2025"),
        "darwin": Path("/Applications/Maxon Cinema 4D 2025"),
        "linux": Path("/opt/maxon/cinema4d-2025"),
    },
}


def _platform_key() -> str:
    if sys.platform == "win32":
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


@pytest.fixture
def cinema4d_location() -> Path:
    """Resolve the Cinema 4D install location.

    Checks in order:
    1. C4D_LOCATION env var (explicit path set by the engineer)
    2. C4D_VERSION env var (CI-only — derives path from version + platform)
    3. Scan known default paths (fallback for local dev without any env vars)
    """
    if "C4D_LOCATION" in os.environ:
        return Path(os.environ["C4D_LOCATION"])

    platform_key = _platform_key()

    version = os.environ.get("C4D_VERSION")
    if version and version in _C4D_DEFAULT_PATHS:
        default_path = _C4D_DEFAULT_PATHS[version][platform_key]
        if default_path.exists():
            print(f"Using Cinema 4D {version} at: {default_path}")
            os.environ["C4D_LOCATION"] = str(default_path)
            return default_path

    for v in _C4D_DEFAULT_PATHS:
        default_path = _C4D_DEFAULT_PATHS[v][platform_key]
        if default_path.exists():
            print(f"Found Cinema 4D at default path: {default_path}")
            os.environ["C4D_LOCATION"] = str(default_path)
            return default_path

    raise EnvironmentError(
        "Cinema 4D location not found. Set C4D_LOCATION to the Cinema 4D install directory, "
        "or set C4D_VERSION to a supported version (e.g., 2025, 2026)."
    )


@pytest.fixture(autouse=True)
def _set_c4d_python_path():
    """Set C4DPYTHONPATH311 so c4dpy can find packages installed in the hatch venv."""
    project_src = str(Path(__file__).parent.parent.parent / "src")
    site_pkgs = site.getsitepackages()
    win32_paths: list[str] = []
    for p in site_pkgs:
        for subdir in ["win32", "win32/lib"]:
            d = Path(p) / subdir
            if d.exists():
                win32_paths.append(str(d))
    all_paths = [project_src] + site_pkgs + win32_paths
    existing = os.environ.get("C4DPYTHONPATH311", "")
    new_paths = os.pathsep.join(p for p in all_paths if p and p not in existing)
    os.environ["C4DPYTHONPATH311"] = (
        f"{new_paths}{os.pathsep}{existing}" if existing else new_paths
    )
    print(f"C4DPYTHONPATH311={os.environ.get('C4DPYTHONPATH311')}")

    for p in site_pkgs:
        pywin32_sys = Path(p) / "pywin32_system32"
        if pywin32_sys.exists():
            os.environ["PATH"] = str(pywin32_sys) + os.pathsep + os.environ.get("PATH", "")
            break


@pytest.fixture
def test_scenes_folder_location() -> Path:
    return Path(__file__).parent / "test_scenes"


# Cinema 4D's bundled Python injects this on every interpreter start and
# patches botocore's _urljoin so the `management.` host prefix that
# Deadline applies to every API call is dropped. Without it, requests
# would hit `http://management.127.0.0.1:<port>/...` and miss the mock.
_HOST_PREFIX_SHIM = textwrap.dedent(
    """
    import botocore.awsrequest as _ar
    _orig = _ar._urljoin
    def _urljoin(endpoint_url, url_path, host_prefix):
        return _orig(endpoint_url, url_path, None)
    _ar._urljoin = _urljoin
    """
).strip() + "\n"


@pytest.fixture
def mock_deadline_farm() -> Iterator[dict]:
    """Spin up an in-memory Deadline Cloud + STS HTTP server pair, seed a
    farm + queue, write a tmp deadline-client config that points at them,
    and yield the env vars needed by a child process (Cinema 4D).

    The submitter dialog talks to:
      * sts:GetCallerIdentity (auth probe) → mock STS server
      * deadline:ListQueueEnvironments + GetQueue + GetFarm → mock Deadline server

    Both run on 127.0.0.1 with ephemeral ports, daemon threads, and shut
    down on fixture teardown.
    """
    farm = MockDeadlineFarm()
    farm_id = farm.farm_id
    queue_id = farm.queue_id

    deadline_server, deadline_url = start_deadline_server(farm)
    sts_server, sts_url = start_sts_server()

    tmpdir = Path(tempfile.mkdtemp(prefix="c4d-mock-deadline-"))
    config_path = tmpdir / "deadline_config"
    config_path.write_text(
        "[profile-(default)]\n"
        "aws_profile_name = (default)\n"
        "\n"
        "[profile-(default) defaults]\n"
        f"farm_id = {farm_id}\n"
        "\n"
        f"[profile-(default) {farm_id} defaults]\n"
        f"queue_id = {queue_id}\n"
        "\n"
        "[telemetry]\n"
        "opt_out = true\n",
        encoding="utf-8",
    )

    shim_dir = tmpdir / "shim"
    shim_dir.mkdir()
    (shim_dir / "sitecustomize.py").write_text(_HOST_PREFIX_SHIM, encoding="utf-8")

    env = {
        "AWS_ENDPOINT_URL_DEADLINE": deadline_url,
        "AWS_ENDPOINT_URL_STS": sts_url,
        "AWS_ACCESS_KEY_ID": "ACCESSKEY",
        "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-west-2",
        "DEADLINE_CONFIG_FILE_PATH": str(config_path),
    }

    # Also point the parent test process at the tmp config so that
    # override_job_history_dir (via deadline.client.config.set_setting)
    # writes to the same file the child Cinema 4D process reads.
    prev_config_env = os.environ.get("DEADLINE_CONFIG_FILE_PATH")
    os.environ["DEADLINE_CONFIG_FILE_PATH"] = str(config_path)

    try:
        yield {
            "farm": farm,
            "farm_id": farm_id,
            "queue_id": queue_id,
            "deadline_url": deadline_url,
            "sts_url": sts_url,
            "shim_dir": str(shim_dir),
            "env": env,
        }
    finally:
        if prev_config_env is None:
            os.environ.pop("DEADLINE_CONFIG_FILE_PATH", None)
        else:
            os.environ["DEADLINE_CONFIG_FILE_PATH"] = prev_config_env
        deadline_server.shutdown()
        deadline_server.server_close()
        sts_server.shutdown()
        sts_server.server_close()
        from shutil import rmtree

        rmtree(tmpdir, ignore_errors=True)
