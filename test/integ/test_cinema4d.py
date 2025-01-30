
from pathlib import Path
import pytest
import json
import subprocess
from typing import Any
import os
import shutil

def run_command(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    print(f"Args list: {args}")
    output = subprocess.run(args, capture_output=True)

    # assert len(output.stdout) == -1, f"The output: {output}"
    # print(f"Ran the following: {' '.join(output.args)}")
    print(f"\nstdout:\n\n{output.stdout.decode('utf-8', errors='replace')}")
    print(f"\nstderr:\n\n{output.stderr.decode('utf-8', errors='replace')}")

    return output

def assert_is_valid_job_bundle(template_location: Path) -> None:
    output = run_command(["openjd", "check", str(template_location), "--output", "json"])

    output_json = json.loads(output.stdout)

    assert output_json["status"] == "success"

def create_c4d_job_bundle(cinema4d_location: Path, scene_script_location: Path, path_to_create_job_bundle: Path) -> None:
    run_command(
        [cinema4d_location, scene_script_location, path_to_create_job_bundle]
    )

def assert_expected_job_bundle_and_generated_job_bundle_are_equal(dir1_path: Path, dir2_path: Path) -> bool:
    """
    Compare files in two directories and report differences with detailed diff output.
    
    Args:
        dir1 (Path): Path to first directory
        dir2 (Path): Path to second directory
    
    Returns:
        dict: Dictionary containing comparison results and diffs
    """
    results = {
        'files_only_in_dir1': [],
        'files_only_in_dir2': [],
        'different_content': [],
        'identical_files': [],
    }
    
    # Get list of files in both directories
    dir1_files = set(f.name for f in dir1_path.glob('*') if f.is_file())
    dir2_files = set(f.name for f in dir2_path.glob('*') if f.is_file())
    
    # Compare contents of files that exist in both directories
    common_files = dir1_files.intersection(dir2_files)
    
    for file in common_files:
        file1_path = dir1_path / file
        file2_path = dir2_path / file
        
        # Read files and compare their contents directly
        with open(file1_path, 'r', encoding='utf-8') as f1, \
                open(file2_path, 'r', encoding='utf-8') as f2:
            content1 = f1.read().strip()  # strip() removes trailing whitespace
            content2 = f2.read().strip()
            
            # Normalize line endings
            content1 = content1.replace('\r\n', '\n')
            content2 = content2.replace('\r\n', '\n')
            
            if content1 == content2:
                results['identical_files'].append(file)
            else:
                results['different_content'].append(file)

    assert len(results['different_content']) == 0
    assert len(results['identical_files']) == 3
    assert "template.yaml" in results['identical_files']
    assert "parameter_values.yaml" in results['identical_files']
    assert "asset_references.yaml" in results['identical_files']
    
    return results
    

@pytest.mark.submitter
def test_submitter(
    cinema4d_location: Path, test_scenes_folder_location: Path,
) -> None:
    """
    Test the submitter code.

    Args:
        test_scenes_folder_location (Path): The location of the test scenes.
    """

    test_scene_script_location = test_scenes_folder_location / "redshift_textured_with_nonascii_characters" / "scene" / "scene.py"
    job_bundle_generated = test_scenes_folder_location / "redshift_textured_with_nonascii_characters" / "generated_bundle"
    os.makedirs(job_bundle_generated)

    create_c4d_job_bundle(cinema4d_location, test_scene_script_location, job_bundle_generated)

    assert_is_valid_job_bundle(job_bundle_generated / "template.yaml")

    expected_job_bundle = test_scenes_folder_location / "redshift_textured_with_nonascii_characters" / "expected_job_bundle"
    assert_expected_job_bundle_and_generated_job_bundle_are_equal(job_bundle_generated, expected_job_bundle)

    # Clean up if the test was successful
    shutil.rmtree(job_bundle_generated, ignore_errors=True)