# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

from __future__ import annotations

import re
import shutil
import subprocess

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from _project import get_project_dict, get_dependencies, Dependency

SUPPORTED_PYTHON_VERSIONS = ["3.10", "3.11", "3.12", "3.13"]
SUPPORTED_PLATFORMS = ["Windows", "Linux", "Darwin"]
NATIVE_DEPENDENCIES = ["xxhash", "psutil"]

# Qt modules to keep - matches the vetted set from deadline-cloud PR #1021.
# Only these modules have been reviewed for licensing compliance (LGPL).
# Direct dependencies:
#   QtCore, QtGui, QtWidgets - used by deadline.client.ui via qtpy
#   QtDBus - required by Qt on Linux/macOS for system integration
#   QtSvg - SVG icon support
# Transitive dependencies (pulled in by Qt platform plugins):
#   QtXcbQpa - X11 platform plugin (Linux)
#   QtWaylandClient, QtWaylandEglClientHwIntegration, QtWlShellIntegration - Wayland (Linux)
#   QtOpenGL, QtEglFSDeviceIntegration, QtEglFsKmsSupport - transitive deps of platform plugins
QT_MODULES_TO_KEEP = {
    "QtCore",
    "QtGui",
    "QtWidgets",
    "QtSvg",
    "QtDBus",
    "QtXcbQpa",
    "QtWaylandClient",
    "QtWaylandEglClientHwIntegration",
    "QtWlShellIntegration",
    "QtOpenGL",
    "QtEglFSDeviceIntegration",
    "QtEglFsKmsSupport",
}

# Qt plugin directories to keep
QT_PLUGIN_DIRS_TO_KEEP = {"platforms", "styles", "iconengines", "wayland-shell-integration"}
# Image format plugins to keep (SVG only)
QT_IMAGEFORMAT_PLUGINS_TO_KEEP = {"libqsvg", "qsvg"}


def _get_package_version_regex(package: str) -> re.Pattern:
    return re.compile(rf"^{re.escape(package)} *(.*)$")


def _get_package_version(package: str, install_path: Path) -> str:
    version_regex = _get_package_version_regex(package)
    pip_args = ["pip", "list", "--path", str(install_path)]
    output = subprocess.run(pip_args, check=True, capture_output=True).stdout.decode("utf-8")
    for line in output.split("\n"):
        match = version_regex.match(line)
        if match:
            return match.group(1)
    raise Exception(f"Could not find version for package {package}")


def _build_base_environment(working_directory: Path, dependencies: list[Dependency]) -> Path:
    (working_directory / "base_env").mkdir()
    base_env_path = working_directory / "base_env"
    dependencies_for_pip = [d.for_pip() for d in dependencies]
    base_env_pip_args = [
        "pip",
        "install",
        "--target",
        str(base_env_path),
        "--only-binary=:all:",
        *dependencies_for_pip,
    ]
    subprocess.run(base_env_pip_args, check=True)
    return base_env_path


def _download_native_dependencies(working_directory: Path, base_env: Path) -> list[Path]:
    versioned_native_dependencies = [
        f"{package_name}=={_get_package_version(package_name, base_env)}"
        for package_name in NATIVE_DEPENDENCIES
    ]
    native_dependency_paths = []
    for version in SUPPORTED_PYTHON_VERSIONS:
        native_dependency_path = working_directory / "native" / f"{version.replace('.', '_')}"
        native_dependency_paths.append(native_dependency_path)
        native_dependency_path.mkdir(parents=True)
        native_dependency_pip_args = [
            "pip",
            "install",
            "--target",
            str(native_dependency_path),
            "--python-version",
            version,
            "--only-binary=:all:",
            *versioned_native_dependencies,
        ]
        subprocess.run(native_dependency_pip_args, check=True)
    return native_dependency_paths


def _copy_native_to_base_env(base_env: Path, native_dependency_paths: list[Path]) -> None:
    for native_dependency_path in native_dependency_paths:
        for file in native_dependency_path.rglob("*"):
            if file.is_file():
                relative = file.relative_to(native_dependency_path)
                in_base_env = base_env / relative
                if not in_base_env.exists():
                    in_base_env.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(str(file), str(in_base_env))


def _get_zip_path(working_directory: Path, project_dict: dict[str, Any]) -> Path:
    if "project" not in project_dict:
        raise Exception("pyproject.toml is missing project section")
    if "name" not in project_dict["project"]:
        raise Exception("pyproject.toml is missing name section")
    transformed_project_name = (
        f"{project_dict['project']['name'].replace('-', '_')}_submitter-deps.zip"
    )
    return working_directory / transformed_project_name


def _filter_qt_modules(base_env: Path) -> None:
    """Remove unused Qt modules from the PySide6 installation for licensing compliance.

    PySide6-Essentials installs more Qt modules than we need. We only keep the
    modules that have been reviewed for LGPL compliance, matching the vetted set
    from deadline-cloud's installer (PR #1021 allowlist.py).
    """
    pyside_dir = base_env / "PySide6"
    if not pyside_dir.exists():
        print("WARNING: PySide6 directory not found in base_env, skipping Qt filtering")
        return

    removed_count = 0

    # Remove unused Qt shared libraries (Linux: libQt6*.so*, Windows: Qt6*.dll)
    for pattern in ("libQt6*.so*", "Qt6*.dll"):
        for lib in pyside_dir.glob(pattern):
            module_name = lib.name.split(".")[0].replace("libQt6", "Qt").replace("Qt6", "Qt")
            if module_name not in QT_MODULES_TO_KEEP:
                lib.unlink()
                print(f"  Removed unused Qt library: {lib.name}")
                removed_count += 1

    # Remove unused Qt shared libraries in Qt/lib/ (Linux .so, macOS .framework)
    qt_lib_dir = pyside_dir / "Qt" / "lib"
    if qt_lib_dir.exists():
        for item in list(qt_lib_dir.iterdir()):
            if item.name.endswith(".framework"):
                module_name = item.name.replace(".framework", "")
                if module_name not in QT_MODULES_TO_KEEP:
                    shutil.rmtree(item)
                    print(f"  Removed unused Qt framework: {item.name}")
                    removed_count += 1
            elif item.name.startswith("libQt6") and (item.is_file() or item.is_symlink()):
                module_name = item.name.split(".")[0].replace("libQt6", "Qt")
                if module_name not in QT_MODULES_TO_KEEP:
                    item.unlink()
                    print(f"  Removed unused Qt library: {item.name}")
                    removed_count += 1

    # Remove unused Python binding files (.abi3.so / .pyd)
    for pattern in ("Qt*.abi3.so", "Qt*.pyd"):
        for binding in pyside_dir.glob(pattern):
            module_name = binding.name.split(".")[0]
            if module_name not in QT_MODULES_TO_KEEP:
                binding.unlink()
                print(f"  Removed unused Qt binding: {binding.name}")
                removed_count += 1

    # Remove unused Qt plugins
    for plugins_candidate in (pyside_dir / "Qt" / "plugins", pyside_dir / "plugins"):
        if not plugins_candidate.exists():
            continue
        for plugin_dir in list(plugins_candidate.iterdir()):
            if not plugin_dir.is_dir():
                continue
            if plugin_dir.name == "imageformats":
                # Keep only SVG image format plugin
                for plugin in list(plugin_dir.iterdir()):
                    plugin_base = plugin.stem.split(".")[0]
                    if plugin_base not in QT_IMAGEFORMAT_PLUGINS_TO_KEEP:
                        plugin.unlink()
                        print(f"  Removed unused imageformat plugin: {plugin.name}")
                        removed_count += 1
            elif plugin_dir.name not in QT_PLUGIN_DIRS_TO_KEEP:
                shutil.rmtree(plugin_dir)
                print(f"  Removed unused Qt plugin directory: {plugin_dir.name}/")
                removed_count += 1

    # Remove Qt translations (not needed for our UI)
    for translations_dir in (pyside_dir / "Qt" / "translations", pyside_dir / "translations"):
        if translations_dir.exists():
            shutil.rmtree(translations_dir)
            print(f"  Removed Qt translations directory")
            removed_count += 1

    print(f"  Qt filtering complete: removed {removed_count} unused items")


def _zip_bundle(base_env: Path, zip_path: Path) -> None:
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", str(base_env))


def _copy_zip_to_destination(zip_path: Path) -> Path:
    dependency_bundle_dir = Path.cwd() / "dependency_bundle"
    dependency_bundle_dir.mkdir(exist_ok=True)
    zip_destination = dependency_bundle_dir / zip_path.name
    if zip_destination.exists():
        zip_destination.unlink()
    shutil.copy(str(zip_path), str(zip_destination))

    return zip_destination


def build_deps_bundle() -> None:
    with TemporaryDirectory() as working_directory:
        working_directory = Path(working_directory)
        project_dict = get_project_dict()
        dependencies: list[Dependency] = get_dependencies(project_dict)
        deps_noopenjd: list[Dependency] = filter(
            lambda dep: not dep.name.startswith("openjd"), dependencies
        )
        base_env = _build_base_environment(working_directory, deps_noopenjd)
        native_dependency_paths = _download_native_dependencies(working_directory, base_env)
        _copy_native_to_base_env(base_env, native_dependency_paths)
        print("Filtering unused Qt modules for licensing compliance...")
        _filter_qt_modules(base_env)
        zip_path = _get_zip_path(working_directory, project_dict)
        _zip_bundle(base_env, zip_path)
        print(list(working_directory.glob("*")))
        _copy_zip_to_destination(zip_path)


if __name__ == "__main__":
    build_deps_bundle()
