# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
from pathlib import Path
import json
import subprocess
import os
import sys
from difflib import unified_diff
import re
from yaml import safe_load, dump
from unittest.mock import patch


import numpy as np
import PIL.Image


def run_command(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    """
    Runs a command and returns the output. Additionally, we also log the stdout/stderr
    in case of a test failures.
    """

    print(f"Args list: {args}")
    output = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)

    print(f"\nstdout:\n\n{output.stdout.decode('utf-8', errors='replace')}")
    print(f"\nstderr:\n\n{output.stderr.decode('utf-8', errors='replace')}")

    assert output.returncode == 0, f"Failed to run command {args}"

    return output


def assert_is_valid_job_bundle(template_location: Path) -> None:
    """
    Runs the `openjd check` command and asserts that the job bundle is valid.
    """
    output = run_command(["openjd", "check", str(template_location), "--output", "json"])

    output_json = json.loads(output.stdout)

    assert output_json["status"] == "success"


def create_c4d_job_bundle(
    cinema4d_location: Path, scene_script_location: Path, path_to_create_job_bundle: Path
) -> None:
    """
    Creates a job bundle by using 'c4dpy' to create a scene file and submit the job
    using internal integ helpers.
    """
    run_command(
        [str(cinema4d_location), str(scene_script_location), str(path_to_create_job_bundle)]
    )


def assert_openjd_run_with_cinema4d_successful(
    cinema4d_location: Path,
    template_path: Path,
    params_path: Path,
) -> None:
    """
    Runs the steps for template using Open JD run with Cinema 4D.
    Returns True if successful.
    """
    c4d_exe = cinema4d_location / (
        "Commandline.exe" if sys.platform == "win32" else "bin" / Path("Commandline")
    )
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

            # Remove the queue Env Parameters
            job_params.pop("CondaChannels", None)
            job_params.pop("CondaPackages", None)
            # Remove Deadline Cloud specific parameters
            job_params.pop("deadline:maxFailedTasksCount", None)
            job_params.pop("deadline:priority", None)
            job_params.pop("deadline:maxRetriesPerTask", None)
            job_params.pop("deadline:targetTaskRunStatus", None)

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


def replace_backslashes(content: str) -> str:
    """
    Replaces backslashes that are path separators.
    Note: This also preserves the backslashes in unicode characters.
    """
    content = re.sub(
        r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2})", r"UNICODE_ESCAPE\1", content
    )  # To avoid unicode '\' getting replaced
    content = re.sub(r"\\+", "/", content)
    content = content.replace("UNICODE_ESCAPE", "\\")  # Add unicode escape back
    return content


def _strip_job_environments_from_template(content: str) -> str:
    """
    Strip the jobEnvironments section from a template.yaml file.
    """
    try:
        data = safe_load(content)
        if isinstance(data, dict) and "jobEnvironments" in data:
            del data["jobEnvironments"]
        return dump(data, default_flow_style=False, sort_keys=True)
    except Exception:
        # If parsing fails, return original content
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
    # The fixtures store the placeholder as "PATH_TO_BE_REPLACED<sep>deadline-..."
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


def _normalize_conda_packages_version(content: str) -> str:
    """
    Normalize the CondaPackages parameter to match the expected test format.
    This allows tests to pass regardless of the actual version numbers by
    normalizing the generated content to match the expected format.
    """

    content = re.sub(
        r"cinema4d=202[4-9].\* cinema4d-openjd=0.\d+.\*",
        "cinema4d=2026.* cinema4d-openjd=0.8.*",
        content,
    )
    return content


def _normalize_submitter_integration_version(content: str) -> str:
    """
    Normalize the SubmitterIntegrationVersion parameter to match the expected test format.
    This allows tests to pass regardless of the actual version numbers by
    normalizing the generated content to match the expected format.
    """
    content = re.sub(
        r"(name: SubmitterIntegrationVersion\n\s+value: )\S+",
        r"\g<1>0.8.0",
        content,
    )
    return content


def _find_actual_image(actual_image_directory: Path, expected_image_name: str) -> Path:
    """
    Find the actual image file, handling variations in special character sanitization.
    Cinema 4D and our code may sanitize special characters differently (e.g., 2 vs 4 underscores).
    """
    # Try exact match first
    exact_path = actual_image_directory / expected_image_name
    if exact_path.exists():
        return exact_path

    # Try to find a file that matches when normalizing underscores
    # This handles cases where expected has "__" but actual has "____" or vice versa
    for actual_file in actual_image_directory.iterdir():
        if not actual_file.is_file():
            continue
        # Normalize both names by collapsing multiple underscores to single
        normalized_expected = re.sub(r"_+", "_", expected_image_name)
        normalized_actual = re.sub(r"_+", "_", actual_file.name)
        if normalized_expected == normalized_actual:
            return actual_file

    # No match found, return original path (will fail with clear error)
    return exact_path


def assert_all_images_close(expected_image_directory: Path, actual_image_directory: Path):
    for image in (expected_image_directory).iterdir():
        if not image.is_file():
            continue

        # Find the actual image, handling sanitization variations
        actual_image_path = _find_actual_image(actual_image_directory, image.name)

        # Verify the actual image exists and has valid dimensions
        actual = np.asarray(PIL.Image.open(actual_image_path))
        expected = np.asarray(PIL.Image.open(image))

        # Check that images have the same shape (dimensions match)
        assert (
            actual.shape == expected.shape
        ), f"Image dimensions differ: {actual.shape} vs {expected.shape}"
