# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# This conftest mirrors test/integ/conftest.py. Once the xa11y-driven test
# replaces the existing rendering integ tests, this folder will be renamed
# to test/integ/ and the two files will be merged.

import pytest
import os
import site
import sys

from pathlib import Path

# Default install paths per version and platform.
# Order matters: when scanning for an installed C4D without C4D_LOCATION /
# C4D_VERSION set, the first match wins. Newest version first so dev boxes
# with both installed get 2026.
_C4D_DEFAULT_PATHS = {
    "2026": {
        "win32": Path(r"C:\Program Files\Maxon Cinema 4D 2026"),
        "linux": Path("/opt/maxon/cinema4d-2026"),
    },
    "2025": {
        "win32": Path(r"C:\Program Files\Maxon Cinema 4D 2025"),
        "linux": Path("/opt/maxon/cinema4d-2025"),
    },
}


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

    platform_key = "win32" if sys.platform == "win32" else "linux"

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
