# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Set up locally built adaptor wheels on a Deadline Cloud worker."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from importlib.metadata import distributions
from pathlib import Path

_EXPECTED_WHEEL_PREFIXES = (
    "openjd_adaptor_runtime-",
    "deadline-",
    "deadline_cloud_for_cinema_4d-",
)


def _find_wheels(wheels_dir: Path) -> list[Path]:
    wheels = sorted(wheels_dir.glob("*.whl"))
    selected: list[Path] = []

    for prefix in _EXPECTED_WHEEL_PREFIXES:
        matches = [wheel for wheel in wheels if wheel.name.startswith(prefix)]
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected exactly one wheel matching '{prefix}*.whl' in {wheels_dir}, "
                f"found {[wheel.name for wheel in matches]}"
            )
        selected.append(matches[0])

    if len(wheels) != len(selected):
        unexpected = sorted(set(wheels) - set(selected))
        raise RuntimeError(
            "The adaptor wheels directory contains unexpected wheels: "
            + ", ".join(wheel.name for wheel in unexpected)
        )

    return selected


def _get_venv_paths(venv_dir: Path, adaptor_name: str) -> tuple[Path, Path, Path]:
    if os.name == "nt":
        bin_dir = venv_dir / "Scripts"
        return bin_dir, bin_dir / "python.exe", bin_dir / f"{adaptor_name}.exe"

    bin_dir = venv_dir / "bin"
    return bin_dir, bin_dir / "python", bin_dir / adaptor_name


def _get_site_packages(venv_python: Path) -> Path:
    result = subprocess.run(
        [
            str(venv_python),
            "-c",
            "import sysconfig; print(sysconfig.get_paths()['purelib'])",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def _get_distribution_version(site_packages: Path, distribution_name: str) -> str:
    canonical_name = re.sub(r"[-_.]+", "-", distribution_name).lower()
    for distribution in distributions(path=[str(site_packages)]):
        installed_name = distribution.metadata.get("Name")
        if installed_name and re.sub(r"[-_.]+", "-", installed_name).lower() == canonical_name:
            return distribution.version
    raise RuntimeError(f"Could not find '{distribution_name}' in {site_packages}")


def _emit_environment_changes(
    before: dict[str, str],
    *,
    venv_dir: Path,
    venv_bin: Path,
    site_packages: Path,
) -> None:
    after = dict(before)
    after["PATH"] = os.pathsep.join(filter(None, (str(venv_bin), before.get("PATH", ""))))
    after["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(site_packages), before.get("PYTHONPATH", "")))
    )
    after["VIRTUAL_ENV"] = str(venv_dir)
    after.pop("PYTHONHOME", None)

    for key, value in sorted(after.items()):
        if value != before.get(key):
            print(f"openjd_env: {key}={value}")

    for key in sorted(before):
        if key not in after:
            print(f"openjd_unset_env: {key}")


def main() -> None:
    working_dir = Path(r"{{Session.WorkingDirectory}}")
    wheels_dir = Path(r"{{Param.OverrideAdaptorWheels}}")
    adaptor_name = r"{{Param.OverrideAdaptorName}}"
    before_environment = dict(os.environ)

    print(f"Setting up {adaptor_name} from attached wheels on {sys.platform}")
    wheels = _find_wheels(wheels_dir)
    for wheel in wheels:
        print(f"  {wheel.name}")

    venv_dir = working_dir / "adaptor-venv"
    print(f"Creating adaptor virtual environment at {venv_dir}")
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv_dir)],
        check=True,
    )

    venv_bin, venv_python, adaptor_executable = _get_venv_paths(venv_dir, adaptor_name)
    subprocess.run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            *[str(wheel) for wheel in wheels],
        ],
        check=True,
    )

    if not adaptor_executable.is_file():
        raise RuntimeError(
            f"The override adaptor '{adaptor_name}' was not installed at {adaptor_executable}"
        )

    site_packages = _get_site_packages(venv_python)
    adaptor_version = _get_distribution_version(site_packages, "deadline-cloud-for-cinema-4d")
    print(
        "ADAPTOR_OVERRIDE_READY "
        f"executable={adaptor_executable} "
        f"package=deadline-cloud-for-cinema-4d version={adaptor_version}"
    )

    _emit_environment_changes(
        before_environment,
        venv_dir=venv_dir,
        venv_bin=venv_bin,
        site_packages=site_packages,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ADAPTOR_OVERRIDE_FAILED: {exc}", file=sys.stderr)
        raise
