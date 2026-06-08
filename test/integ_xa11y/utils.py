# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
import contextlib
import json
import os
import re
import site
import subprocess
import sys
import time
from datetime import datetime
from difflib import unified_diff
from pathlib import Path
from unittest.mock import patch

import numpy as np
import PIL.Image
from yaml import dump, safe_load


_T0 = time.monotonic()


def log(msg: str) -> None:
    """Verbose trace log so failures show where the test got stuck."""
    elapsed = time.monotonic() - _T0
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[integ_xa11y {ts} +{elapsed:6.2f}s] {msg}", flush=True)


def run_command(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Run a command and return the output. Logs stdout/stderr for debugging."""
    print(f"Args list: {args}")
    output = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
    print(f"\nstdout:\n\n{output.stdout.decode('utf-8', errors='replace')}")
    print(f"\nstderr:\n\n{output.stderr.decode('utf-8', errors='replace')}")
    assert output.returncode == 0, f"Failed to run command {args}"
    return output


def assert_is_valid_job_bundle(template_location: Path) -> None:
    """Run `openjd check` and assert the bundle is valid."""
    output = run_command(["openjd", "check", str(template_location), "--output", "json"])
    output_json = json.loads(output.stdout)
    assert output_json["status"] == "success"


def assert_openjd_run_with_cinema4d_successful(
    cinema4d_location: Path,
    template_path: Path,
    params_path: Path,
) -> None:
    """Run each step in the template via `openjd run` against Cinema 4D Commandline."""
    c4d_exe = resolve_c4d_exe(cinema4d_location, "Commandline")
    test_env = {
        "C4D_COMMANDLINE_EXECUTABLE": str(c4d_exe),
        "CINEMA4D_ADAPTOR_TESTING": "True",
    }

    with patch.dict(os.environ, test_env):
        with open(template_path, encoding="utf-8") as f:
            template = safe_load(f)

        with open(params_path, encoding="utf-8") as f:
            parameter_values = safe_load(f)["parameterValues"]
            job_params = {item["name"]: item["value"] for item in parameter_values}

            # Remove queue env parameters and Deadline Cloud–specific parameters.
            for k in (
                "CondaChannels",
                "CondaPackages",
                "deadline:maxFailedTasksCount",
                "deadline:priority",
                "deadline:maxRetriesPerTask",
                "deadline:targetTaskRunStatus",
            ):
                job_params.pop(k, None)

        for step in template["steps"]:
            output = run_command(
                [
                    "openjd",
                    "run",
                    str(template_path),
                    "--step",
                    step["name"],
                    "--job-param",
                    json.dumps(job_params),
                ]
            )
            assert output.returncode == 0


def resolve_c4d_exe(cinema4d_location: Path, name: str) -> Path:
    """Resolve a Cinema 4D executable by name (e.g. "Cinema 4D", "c4dpy", "Commandline")."""
    if sys.platform == "win32":
        exe = cinema4d_location / f"{name}.exe"
    elif sys.platform == "darwin":
        exe = cinema4d_location / f"{name}.app" / "Contents" / "MacOS" / name
    else:
        exe = cinema4d_location / name
    if not exe.exists():
        raise FileNotFoundError(f"{name} executable not found at {exe}")
    log(f"resolved {name}: {exe}")
    return exe


def build_submitter_pythonpath(repo_root: Path) -> str:
    """Same recipe as test/integ/conftest.py:_set_c4d_python_path —
    point C4DPYTHONPATH<py> at the editable submitter source plus the
    venv's site-packages so PySide6 / qtpy / deadline-client resolve."""
    parts: list[str] = [str(repo_root / "src")]
    parts.extend(site.getsitepackages())
    if sys.platform == "win32":
        for sp in site.getsitepackages():
            for sub in ("win32", "win32/lib"):
                d = Path(sp) / sub
                if d.exists():
                    parts.append(str(d))
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return os.pathsep.join(out)


def build_cinema4d_scene(
    c4dpy_location: Path,
    scene_script_location: Path,
    scene_dir: Path,
    scene_name: str,
) -> Path:
    """Run the scene-building script inside c4dpy. Returns the saved .c4d path.

    scene_dir is expected to already exist (the caller creates it), and the
    script is expected to save the scene as scene_name within it.
    """
    result = subprocess.run(
        [str(c4dpy_location), str(scene_script_location), str(scene_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    # c4dpy frequently exits non-zero on shutdown after a successful script
    # (Windows, post-script teardown). The bundle file existence is the
    # source of truth — same approach as the crowecawcaw e2e driver.
    scene = scene_dir / scene_name
    assert scene.is_file(), (
        f"scene.py did not save expected file at {scene} "
        f"(c4dpy exit code {result.returncode})"
    )
    return scene


def kill_proc(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        log(f"C4D process pid={proc.pid} already exited (rc={proc.returncode})")
        return
    log(f"terminating C4D process pid={proc.pid}")
    try:
        proc.terminate()
        proc.wait(timeout=10)
        log(f"C4D process pid={proc.pid} terminated cleanly")
    except subprocess.TimeoutExpired:
        log(f"C4D process pid={proc.pid} did not respond to terminate, killing")
        proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
        log(f"C4D process pid={proc.pid} killed")


def wait_for_bundle(history_dir: Path, timeout_s: float) -> Path:
    """Return the newest job-history bundle dir under `history_dir`.
    Bundles live at history_dir/<YYYY-mm>/<bundle-name>/."""
    log(f"waiting up to {timeout_s:.0f}s for bundle under {history_dir}")
    deadline_t = time.monotonic() + timeout_s
    last_log = 0.0
    while time.monotonic() < deadline_t:
        candidates = [p for p in history_dir.glob("*/*") if p.is_dir()]
        if candidates:
            bundle = max(candidates, key=lambda p: p.stat().st_mtime)
            log(f"bundle found: {bundle}")
            return bundle
        # Log every 5s while polling so we can see we're still alive.
        now = time.monotonic()
        if now - last_log >= 5.0:
            log(f"still waiting for bundle ({now - (deadline_t - timeout_s):.1f}s elapsed)")
            last_log = now
        time.sleep(0.5)
    raise AssertionError(
        f"No bundle created under {history_dir} within {timeout_s:.0f}s"
    )


@contextlib.contextmanager
def override_job_history_dir(path: Path):
    """The submitter exports to settings.job_history_dir (a persistent
    deadline-client config setting). Override it for the duration of
    the test and restore the user's prior value on the way out."""
    from deadline.client.config import get_setting, set_setting

    previous = get_setting("settings.job_history_dir")
    log(f"override settings.job_history_dir: {previous!r} -> {str(path)!r}")
    set_setting("settings.job_history_dir", str(path))
    try:
        yield
    finally:
        log(f"restore settings.job_history_dir -> {previous!r}")
        set_setting("settings.job_history_dir", previous)


# Below: identical golden-bundle and image comparison helpers as in
# test/integ/utils.py. Kept in lockstep so when this folder replaces
# test/integ/, there's a single source of truth.


def replace_backslashes(content: str) -> str:
    """
    Replaces backslashes that are path separators.
    Note: This also preserves the backslashes in unicode characters.
    """
    content = re.sub(
        r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2})", r"UNICODE_ESCAPE\1", content
    )
    content = re.sub(r"\\+", "/", content)
    content = content.replace("UNICODE_ESCAPE", "\\")
    return content


def _strip_job_environments_from_template(content: str) -> str:
    """Strip the jobEnvironments section from a template.yaml file."""
    try:
        data = safe_load(content)
        if isinstance(data, dict) and "jobEnvironments" in data:
            del data["jobEnvironments"]
        return dump(data, default_flow_style=False, sort_keys=True)
    except Exception:
        return content


def _normalize_conda_packages_version(content: str) -> str:
    return re.sub(
        r"cinema4d=202[4-9].\* cinema4d-openjd=0.\d+.\*",
        "cinema4d=2026.* cinema4d-openjd=0.8.*",
        content,
    )


def _normalize_submitter_integration_version(content: str) -> str:
    """Normalize SubmitterIntegrationVersion to a fixed placeholder. The
    submitter version changes every build (e.g. 0.11.1.post9.g5c549afe6 →
    0.11.1.post9.g4b00ca23b.d20260522), so neither expected nor generated
    is a stable string. Replace both with a fixed value before comparing.

    Matches both YAML form ("value: 0.11.1.post9...") and JSON-in-YAML form
    ('"value": "0.11.1.post9..."') as deadline-yaml-dump may emit either
    depending on the value's contents.
    """
    # YAML form: "name: SubmitterIntegrationVersion\n  value: 0.11..."
    content = re.sub(
        r"(name: SubmitterIntegrationVersion\n\s+value: )\S+",
        r"\g<1>NORMALIZED",
        content,
    )
    # JSON form: '"name": "SubmitterIntegrationVersion", "value": "0.11..."'
    content = re.sub(
        r'("name":\s*"SubmitterIntegrationVersion"\s*,\s*"value":\s*")[^"]*(")',
        r"\1NORMALIZED\2",
        content,
    )
    return content



def assert_expected_job_bundle_and_generated_job_bundle_are_equal(
    expected_job_bundle_dir_path: Path, generated_job_bundle_dir_path: Path
) -> None:
    """
    Assert that the generated job bundle matches with the expected job bundle.
    """

    results: dict[str, list[str]] = {
        "different_content": [],
        "identical_files": [],
    }

    # So that we can replace PATH_TO_BE_REPLACED in the expected job bundle.
    # The fixtures store the placeholder as "PATH_TO_BE_REPLACED/deadline-..."
    # (the separator after the placeholder belongs to the fixture), but
    # split(...)[0] keeps the trailing separator. Strip it so the substitution
    # doesn't produce a doubled separator ("Github Repos//deadline-..."). On
    # Windows the doubled separator was masked because replace_backslashes
    # collapses "\\+" to a single "/", but on POSIX the doubled "/" survived.
    prefix_path = os.path.abspath(expected_job_bundle_dir_path).split(
        "deadline-cloud-for-cinema-4d"
    )[0].rstrip("/\\")

    # Get list of files in both directories
    expected_job_bundle_files = set(
        f.name for f in expected_job_bundle_dir_path.glob("*") if f.is_file()
    )
    generated_job_bundle_files = set(
        f.name for f in generated_job_bundle_dir_path.glob("*") if f.is_file()
    )

    # Compare contents of files that exist in both directories
    common_files = expected_job_bundle_files.intersection(generated_job_bundle_files)

    for file in common_files:
        file1_path = expected_job_bundle_dir_path / file
        file2_path = generated_job_bundle_dir_path / file

        # Read files and compare their contents directly
        with (
            open(file1_path, "r", encoding="utf-8") as f1,
            open(file2_path, "r", encoding="utf-8") as f2,
        ):
            content1 = f1.read().strip()  # strip() removes trailing whitespace
            content2 = f2.read().strip()

        # Normalize line endings
        content1 = content1.replace("\r\n", "\n")
        content2 = content2.replace("\r\n", "\n")

        # Special handling for parameter_values.yaml to normalize version differences.
        # Done on the raw YAML text because the regexes rely on the YAML key/value layout.
        if file == "parameter_values.yaml":
            content1 = _normalize_conda_packages_version(content1)
            content2 = _normalize_conda_packages_version(content2)
            content1 = _normalize_submitter_integration_version(content1)
            content2 = _normalize_submitter_integration_version(content2)

        # For YAML files, parse the document and re-serialize it as single-line JSON
        # BEFORE normalizing path separators. Parsing first lets the YAML parser
        # resolve multi-line double-quoted scalars correctly: PyYAML folds long,
        # space-free paths using escaped line breaks (a trailing "\" at the fold).
        # If replace_backslashes ran on the raw multi-line YAML, it would turn those
        # line-continuation backslashes into "/", changing the parsed value depending
        # on where each file happened to wrap -- which is what broke the non-ASCII
        # path tests. JSON is emitted on a single line, so there are no line
        # continuations left for replace_backslashes to corrupt.
        if file in ("parameter_values.yaml", "asset_references.yaml"):
            content1 = json.dumps(safe_load(content1), sort_keys=True)
            content2 = json.dumps(safe_load(content2), sort_keys=True)

        # Replace the prefix path in the expected job bundle, then normalize separators.
        content1 = content1.replace("PATH_TO_BE_REPLACED", prefix_path)
        content1 = replace_backslashes(content1)
        content2 = replace_backslashes(content2)

        # Special handling for template.yaml to strip job environments.
        # Job environments can contain code that changes frequently
        # We don't want to update all tests every time there's a
        # small change in the job environment code, so we strip it before comparison.
        # We check for the code comparison in our unit tests which should be sufficient.
        if file == "template.yaml":
            content1 = _strip_job_environments_from_template(content1)
            content2 = _strip_job_environments_from_template(content2)

        if content1 == content2:
            results["identical_files"].append(file)
        else:
            results["different_content"].append(file)
            diff = "\n".join(
                unified_diff(content1.splitlines(), content2.splitlines(), lineterm="")
            )
            print(diff)

    assert len(results["different_content"]) == 0
    assert len(results["identical_files"]) == 3
    assert "template.yaml" in results["identical_files"]
    assert "parameter_values.yaml" in results["identical_files"]
    assert "asset_references.yaml" in results["identical_files"]

def _find_actual_image(actual_image_directory: Path, expected_image_name: str) -> Path:
    """Find the actual image, handling underscore-sanitization differences."""
    exact_path = actual_image_directory / expected_image_name
    if exact_path.exists():
        return exact_path
    for actual_file in actual_image_directory.iterdir():
        if not actual_file.is_file():
            continue
        normalized_expected = re.sub(r"_+", "_", expected_image_name)
        normalized_actual = re.sub(r"_+", "_", actual_file.name)
        if normalized_expected == normalized_actual:
            return actual_file
    return exact_path


def assert_all_images_close(expected_image_directory: Path, actual_image_directory: Path) -> None:
    """Assert that every image in the expected dir is present in the actual
    dir with matching dimensions."""
    for image in expected_image_directory.iterdir():
        if not image.is_file():
            continue
        actual_image_path = _find_actual_image(actual_image_directory, image.name)
        actual = np.asarray(PIL.Image.open(actual_image_path))
        expected = np.asarray(PIL.Image.open(image))
        assert actual.shape == expected.shape, (
            f"Image dimensions differ: {actual.shape} vs {expected.shape}"
        )

        # Check that the two images are the same within a tolerance.
        # It's normal for there to be noise in an output image, so it is unlikely that two
        # renders will be exactly the same.
        assert np.allclose(actual, expected, atol=2)
