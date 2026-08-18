# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

import os
from pathlib import Path
from unittest import mock

import pytest

from deadline.cinema4d_submitter.cinema4d_render_submitter import (
    _get_adaptor_override_environment,
)
from deadline.cinema4d_submitter.setup_adaptor_wheels import (
    _emit_environment_changes,
    _find_wheels,
    _get_distribution_version,
    _get_venv_paths,
)

_WHEEL_NAMES = (
    "openjd_adaptor_runtime-0.9.0-py3-none-any.whl",
    "deadline-0.60.4-py3-none-any.whl",
    "deadline_cloud_for_cinema_4d-0.12.1-py3-none-any.whl",
)


def _create_wheels(wheels_dir: Path) -> None:
    wheels_dir.mkdir()
    for wheel_name in _WHEEL_NAMES:
        (wheels_dir / wheel_name).touch()


def test_get_adaptor_override_environment_embeds_cross_platform_setup(tmp_path):
    wheels_dir = tmp_path / "wheels"
    _create_wheels(wheels_dir)

    result = _get_adaptor_override_environment(wheels_dir)

    parameters = {parameter["name"]: parameter for parameter in result["parameterDefinitions"]}
    assert parameters["OverrideAdaptorWheels"]["default"] == str(wheels_dir)
    assert parameters["OverrideAdaptorName"]["default"] == "cinema4d-openjd"

    script = result["environment"]["script"]
    assert script["actions"]["onEnter"] == {
        "command": "python",
        "args": ["{{Env.File.SetupAdaptor}}"],
        "cancelation": {"mode": "NOTIFY_THEN_TERMINATE"},
    }
    setup_script = script["embeddedFiles"][0]["data"]
    assert "ADAPTOR_OVERRIDE_READY" in setup_script
    assert '[sys.executable, "-m", "venv", "--system-site-packages"' in setup_script


def test_get_adaptor_override_environment_rejects_missing_directory(tmp_path):
    wheels_dir = tmp_path / "missing"

    with pytest.raises(RuntimeError, match="wheels directory does not exist"):
        _get_adaptor_override_environment(wheels_dir)


def test_find_wheels_requires_exact_expected_set(tmp_path):
    wheels_dir = tmp_path / "wheels"
    _create_wheels(wheels_dir)

    assert [wheel.name for wheel in _find_wheels(wheels_dir)] == list(_WHEEL_NAMES)

    (wheels_dir / "unexpected-1.0-py3-none-any.whl").touch()
    with pytest.raises(RuntimeError, match="unexpected wheels"):
        _find_wheels(wheels_dir)


@pytest.mark.parametrize(
    ("os_name", "bin_directory", "python_name", "adaptor_name"),
    [
        ("nt", "Scripts", "python.exe", "cinema4d-openjd.exe"),
        ("posix", "bin", "python", "cinema4d-openjd"),
    ],
)
def test_get_venv_paths_for_worker_os(tmp_path, os_name, bin_directory, python_name, adaptor_name):
    venv_dir = tmp_path / "venv"

    with mock.patch(
        "deadline.cinema4d_submitter.setup_adaptor_wheels.os.name",
        os_name,
    ):
        result = _get_venv_paths(venv_dir, "cinema4d-openjd")

    expected_bin = venv_dir / bin_directory
    assert result == (
        expected_bin,
        expected_bin / python_name,
        expected_bin / adaptor_name,
    )


def test_get_distribution_version_ignores_other_site_packages(tmp_path):
    site_packages = tmp_path / "site-packages"
    dist_info = site_packages / "deadline_cloud_for_cinema_4d-1.2.3.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\n" "Name: deadline-cloud-for-cinema-4d\n" "Version: 1.2.3\n",
        encoding="utf8",
    )

    assert _get_distribution_version(site_packages, "deadline_cloud_for_cinema_4d") == "1.2.3"


def test_emit_environment_changes_uses_platform_path_separator(capsys, tmp_path):
    before = {
        "PATH": os.pathsep.join(("base", "bin")),
        "PYTHONPATH": "base-packages",
        "PYTHONHOME": "base-python",
        "UNCHANGED": "value",
    }
    venv_dir = tmp_path / "venv"
    venv_bin = venv_dir / "Scripts"
    site_packages = venv_dir / "Lib" / "site-packages"

    _emit_environment_changes(
        before,
        venv_dir=venv_dir,
        venv_bin=venv_bin,
        site_packages=site_packages,
    )

    output = capsys.readouterr().out.splitlines()
    assert f"openjd_env: PATH={venv_bin}{os.pathsep}{before['PATH']}" in output
    assert f"openjd_env: PYTHONPATH={site_packages}{os.pathsep}{before['PYTHONPATH']}" in output
    assert f"openjd_env: VIRTUAL_ENV={venv_dir}" in output
    assert "openjd_unset_env: PYTHONHOME" in output
    assert all("UNCHANGED" not in line for line in output)
