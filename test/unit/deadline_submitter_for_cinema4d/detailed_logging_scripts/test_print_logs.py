# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from deadline.cinema4d_submitter.detailed_logging_scripts.print_logs import (
    get_conda_prefix,
    _get_redshift_log_paths_windows,
    _get_redshift_log_paths_linux,
    _get_redshift_log_paths,
    _find_log_file,
    _find_redshift_log,
    _get_c4d_detailed_log_paths,
    _find_c4d_detailed_log,
    _get_bug_report_search_path,
    _scan_for_bug_reports,
    _find_bug_reports,
    _print_environment_info,
    _print_logs_by_type,
    _find_and_print_redshift_logs,
    _find_and_print_c4d_detailed_logs,
    _find_and_print_bug_reports,
    _cleanup_temporary_directory,
    _cleanup_environment_variables,
    print_log_file,
    print_detailed_logs,
)


class TestGetCondaPrefix:
    """Test the get_conda_prefix() helper function.

    This function retrieves the CONDA_PREFIX environment variable,
    which is used to determine the primary log file location.
    """

    def test_returns_conda_prefix_when_set(self):
        """Test that correct value is returned when CONDA_PREFIX is set"""
        # GIVEN
        test_prefix = "/opt/conda/env"
        with mock.patch.dict(os.environ, {"CONDA_PREFIX": test_prefix}):
            # WHEN
            result = get_conda_prefix()

            # THEN
            assert result == test_prefix

    def test_returns_empty_string_when_not_set(self):
        """Test that empty string is returned when CONDA_PREFIX is not set"""
        # GIVEN
        with mock.patch.dict(os.environ, {}, clear=True):
            # WHEN
            result = get_conda_prefix()

            # THEN
            assert result == ""


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific tests")
class TestGetRedshiftLogPathsWindows:
    """Test the _get_redshift_log_paths_windows() function."""

    def test_includes_conda_prefix_path(self, capsys):
        """Test that CONDA_PREFIX cinema4d/RedshiftData path is included"""
        # GIVEN
        conda_prefix = r"C:\conda\env"
        with mock.patch.dict(os.environ, {"CONDA_PREFIX": conda_prefix}, clear=True):
            # WHEN
            result = _get_redshift_log_paths_windows()

            # THEN
            expected_path = os.path.join(
                conda_prefix, "cinema4d", "RedshiftData", "Log", "Log.Latest.0", "log.html"
            )
            assert expected_path in result

    def test_includes_custom_localdatapath(self, capsys):
        """Test that REDSHIFT_LOCALDATAPATH is included when set"""
        # GIVEN
        custom_path = r"C:\custom\redshift"
        with mock.patch.dict(os.environ, {"REDSHIFT_LOCALDATAPATH": custom_path}, clear=True):
            # WHEN
            result = _get_redshift_log_paths_windows()
            captured = capsys.readouterr()

            # THEN
            expected_path = os.path.join(custom_path, "Log", "Log.Latest.0", "log.html")
            assert expected_path in result
            assert "Found REDSHIFT_LOCALDATAPATH environment variable" in captured.out

    def test_includes_windows_default_path(self):
        """Test that Windows default C:\\ProgramData\\Redshift path is included"""
        # GIVEN
        with mock.patch.dict(os.environ, {}, clear=True):
            # WHEN
            result = _get_redshift_log_paths_windows()

            # THEN
            expected_path = os.path.join(
                r"C:\ProgramData\Redshift", "Log", "Log.Latest.0", "log.html"
            )
            assert expected_path in result

    def test_returns_unique_paths(self):
        """Test that duplicate paths are removed"""
        # GIVEN
        conda_prefix = r"C:\ProgramData\Redshift"
        with mock.patch.dict(os.environ, {"CONDA_PREFIX": conda_prefix}, clear=True):
            # WHEN
            result = _get_redshift_log_paths_windows()

            # THEN
            # Should not have duplicates even though conda prefix matches default
            assert len(result) == len(set(result))

    def test_prints_message_for_custom_path(self, capsys):
        """Test that message is printed when custom REDSHIFT_LOCALDATAPATH is found"""
        # GIVEN
        custom_path = r"C:\custom\redshift"
        with mock.patch.dict(os.environ, {"REDSHIFT_LOCALDATAPATH": custom_path}, clear=True):
            # WHEN
            _get_redshift_log_paths_windows()
            captured = capsys.readouterr()

            # THEN
            assert "Found REDSHIFT_LOCALDATAPATH environment variable" in captured.out
            assert custom_path in captured.out


@pytest.mark.skipif(sys.platform == "win32", reason="Linux/macOS-specific tests")
class TestGetRedshiftLogPathsLinux:
    """Test the _get_redshift_log_paths_linux() function."""

    def test_includes_conda_prefix_path(self):
        """Test that CONDA_PREFIX redshiftlocaldata path is included"""
        # GIVEN
        conda_prefix = "/opt/conda/env"
        with mock.patch.dict(os.environ, {"CONDA_PREFIX": conda_prefix}, clear=True):
            # WHEN
            result = _get_redshift_log_paths_linux()

            # THEN
            expected_path = os.path.join(
                conda_prefix, "redshiftlocaldata", "log", "log.latest.0", "log.html"
            )
            assert expected_path in result

    def test_includes_custom_localdatapath(self, capsys):
        """Test that REDSHIFT_LOCALDATAPATH is included when set"""
        # GIVEN
        custom_path = "/custom/redshift"
        with mock.patch.dict(os.environ, {"REDSHIFT_LOCALDATAPATH": custom_path}, clear=True):
            # WHEN
            result = _get_redshift_log_paths_linux()
            captured = capsys.readouterr()

            # THEN
            expected_path = os.path.join(custom_path, "log", "log.latest.0", "log.html")
            assert expected_path in result
            assert "Found REDSHIFT_LOCALDATAPATH environment variable" in captured.out

    def test_includes_linux_default_path(self):
        """Test that Linux default ~/redshift path is included"""
        # GIVEN
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("os.path.expanduser", return_value="/home/user"):
                # WHEN
                result = _get_redshift_log_paths_linux()

                # THEN
                expected_path = os.path.join(
                    "/home/user", "redshift", "log", "log.latest.0", "log.html"
                )
                assert expected_path in result

    def test_returns_unique_paths(self):
        """Test that duplicate paths are removed"""
        # GIVEN
        home_dir = "/home/user"
        conda_prefix = os.path.join(home_dir, "redshift")
        with mock.patch.dict(os.environ, {"CONDA_PREFIX": conda_prefix}, clear=True):
            with mock.patch("os.path.expanduser", return_value=home_dir):
                # WHEN
                result = _get_redshift_log_paths_linux()

                # THEN
                # Should not have duplicates
                assert len(result) == len(set(result))

    def test_prints_message_for_custom_path(self, capsys):
        """Test that message is printed when custom REDSHIFT_LOCALDATAPATH is found"""
        # GIVEN
        custom_path = "/custom/redshift"
        with mock.patch.dict(os.environ, {"REDSHIFT_LOCALDATAPATH": custom_path}, clear=True):
            # WHEN
            _get_redshift_log_paths_linux()
            captured = capsys.readouterr()

            # THEN
            assert "Found REDSHIFT_LOCALDATAPATH environment variable" in captured.out
            assert custom_path in captured.out


class TestGetRedshiftLogPaths:
    """Test the _get_redshift_log_paths() platform dispatcher function."""

    def test_calls_windows_function_on_win32(self):
        """Test that _get_redshift_log_paths_windows() is called on win32 platform"""
        # GIVEN
        with mock.patch("sys.platform", "win32"):
            with mock.patch.dict(os.environ, {}, clear=True):
                # WHEN
                result = _get_redshift_log_paths()

                # THEN
                # Should include Windows default path
                assert any(r"C:\ProgramData\Redshift" in path for path in result)

    def test_calls_linux_function_on_linux(self):
        """Test that _get_redshift_log_paths_linux() is called on non-win32 platforms"""
        # GIVEN
        with mock.patch("sys.platform", "linux"):
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("os.path.expanduser", return_value="/home/user"):
                    # WHEN
                    result = _get_redshift_log_paths()

                    # THEN
                    # Should include Linux default path
                    assert any("/home/user/redshift" in path for path in result)


class TestFindLogFile:
    """Test the _find_log_file() generic log finding function."""

    def test_returns_first_found_log(self, capsys):
        """Test that first existing log path is returned"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            log_file.write_text("test log")
            paths = ["/nonexistent/log1.log", str(log_file), "/nonexistent/log2.log"]

            # WHEN
            result = _find_log_file(paths, "test log")
            captured = capsys.readouterr()

            # THEN
            assert len(result) == 1
            assert result[0] == str(log_file)
            assert "Found test log:" in captured.out

    def test_returns_empty_list_when_not_found(self, capsys):
        """Test that empty list is returned when no logs exist"""
        # GIVEN
        paths = ["/nonexistent/log1.log", "/nonexistent/log2.log"]

        # WHEN
        result = _find_log_file(paths, "test log")
        captured = capsys.readouterr()

        # THEN
        assert result == []
        assert "test log not found in any expected location" in captured.out

    def test_prints_checking_messages(self, capsys):
        """Test that checking messages are printed for each path"""
        # GIVEN
        paths = ["/path1/log.log", "/path2/log.log"]

        # WHEN
        _find_log_file(paths, "test log")
        captured = capsys.readouterr()

        # THEN
        assert "Checking for test log at: /path1/log.log" in captured.out
        assert "Checking for test log at: /path2/log.log" in captured.out

    def test_prints_found_message(self, capsys):
        """Test that found message is printed when log is located"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            log_file.write_text("test log")

            # WHEN
            _find_log_file([str(log_file)], "test log")
            captured = capsys.readouterr()

            # THEN
            assert "Found test log:" in captured.out

    def test_prints_not_found_message(self, capsys):
        """Test that not found message is printed when no logs exist"""
        # GIVEN
        paths = ["/nonexistent/log.log"]

        # WHEN
        _find_log_file(paths, "test log")
        captured = capsys.readouterr()

        # THEN
        assert "test log not found in any expected location" in captured.out


class TestFindRedshiftLog:
    """Test the _find_redshift_log() function."""

    def test_uses_platform_specific_paths(self):
        """Test that platform-specific paths from _get_redshift_log_paths() are used"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "redshiftlocaldata" / "log" / "log.latest.0"
            log_dir.mkdir(parents=True)
            log_file = log_dir / "log.html"
            log_file.write_text("redshift log")

            with mock.patch.dict(os.environ, {"CONDA_PREFIX": tmpdir}):
                with mock.patch("sys.platform", "linux"):
                    with mock.patch("os.path.expanduser", return_value=tmpdir):
                        # WHEN
                        result = _find_redshift_log()

                        # THEN
                        assert len(result) == 1
                        assert result[0] == str(log_file)

    def test_returns_log_when_found(self, capsys):
        """Test that log path is returned when found"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "redshiftlocaldata" / "log" / "log.latest.0"
            log_dir.mkdir(parents=True)
            log_file = log_dir / "log.html"
            log_file.write_text("redshift log")

            with mock.patch.dict(os.environ, {"CONDA_PREFIX": tmpdir}):
                with mock.patch("sys.platform", "linux"):
                    with mock.patch("os.path.expanduser", return_value=tmpdir):
                        # WHEN
                        result = _find_redshift_log()

                        # THEN
                        assert len(result) == 1
                        assert result[0] == str(log_file)

    def test_returns_empty_list_when_not_found(self, capsys):
        """Test that empty list is returned when not found"""
        # GIVEN
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("sys.platform", "linux"):
                with mock.patch("os.path.expanduser", return_value="/home/user"):
                    # WHEN
                    result = _find_redshift_log()
                    captured = capsys.readouterr()

                    # THEN
                    assert result == []
                    assert "Redshift log not found in any expected location" in captured.out


class TestGetC4dDetailedLogPaths:
    """Test the _get_c4d_detailed_log_paths() function."""

    def test_returns_conda_prefix_path_when_available(self):
        """Test that CONDA_PREFIX path is returned when available"""
        # GIVEN
        conda_prefix = "/opt/conda/env"
        with mock.patch.dict(os.environ, {"CONDA_PREFIX": conda_prefix}, clear=True):
            # WHEN
            result = _get_c4d_detailed_log_paths()

            # THEN
            assert len(result) == 1
            expected_path = os.path.join(conda_prefix, "c4d_detailed_logs.txt")
            assert result[0] == expected_path

    def test_returns_secure_temp_path_as_fallback(self):
        """Test that C4D_DETAILED_LOG_DIR path is returned as fallback"""
        # GIVEN
        temp_dir = "/tmp/c4d_logs_12345"
        with mock.patch.dict(os.environ, {"C4D_DETAILED_LOG_DIR": temp_dir}, clear=True):
            # WHEN
            result = _get_c4d_detailed_log_paths()

            # THEN
            assert len(result) == 1
            expected_path = os.path.join(temp_dir, "c4d_detailed_logs.txt")
            assert result[0] == expected_path

    def test_returns_empty_list_when_neither_available(self, capsys):
        """Test that empty list is returned when neither location is available"""
        # GIVEN
        with mock.patch.dict(os.environ, {}, clear=True):
            # WHEN
            result = _get_c4d_detailed_log_paths()
            captured = capsys.readouterr()

            # THEN
            assert result == []
            assert "Neither CONDA_PREFIX nor C4D_DETAILED_LOG_DIR is set" in captured.out

    def test_prints_message_when_neither_available(self, capsys):
        """Test that message is printed when neither location is available"""
        # GIVEN
        with mock.patch.dict(os.environ, {}, clear=True):
            # WHEN
            _get_c4d_detailed_log_paths()
            captured = capsys.readouterr()

            # THEN
            assert "Neither CONDA_PREFIX nor C4D_DETAILED_LOG_DIR is set" in captured.out

    def test_matches_setup_logging_priority(self):
        """Test that priority order matches setup_logging.py (CONDA_PREFIX first)"""
        # GIVEN
        conda_prefix = "/opt/conda/env"
        temp_dir = "/tmp/c4d_logs_12345"
        with mock.patch.dict(
            os.environ, {"CONDA_PREFIX": conda_prefix, "C4D_DETAILED_LOG_DIR": temp_dir}
        ):
            # WHEN
            result = _get_c4d_detailed_log_paths()

            # THEN
            # Should only return CONDA_PREFIX path (higher priority)
            assert len(result) == 1
            assert conda_prefix in result[0]
            assert temp_dir not in result[0]


class TestFindC4dDetailedLog:
    """Test the _find_c4d_detailed_log() function."""

    def test_finds_log_in_conda_prefix(self, capsys):
        """Test that log is found in CONDA_PREFIX location"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "c4d_detailed_logs.txt"
            log_file.write_text("Cinema 4D detailed log content")

            with mock.patch.dict(os.environ, {"CONDA_PREFIX": tmpdir}):
                # WHEN
                result = _find_c4d_detailed_log()
                captured = capsys.readouterr()

                # THEN
                assert len(result) == 1
                assert result[0] == str(log_file)
                assert "Found Cinema 4D detailed log:" in captured.out

    def test_finds_log_in_secure_temp(self, capsys):
        """Test that log is found in secure temp directory (C4D_DETAILED_LOG_DIR)"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "c4d_detailed_logs.txt"
            log_file.write_text("Cinema 4D detailed log in temp")

            with mock.patch.dict(os.environ, {"C4D_DETAILED_LOG_DIR": tmpdir}, clear=True):
                # WHEN
                result = _find_c4d_detailed_log()
                captured = capsys.readouterr()

                # THEN
                assert len(result) == 1
                assert result[0] == str(log_file)
                assert "Found Cinema 4D detailed log:" in captured.out

    def test_returns_empty_when_not_found(self, capsys):
        """Test that empty list is returned when log doesn't exist"""
        # GIVEN
        with mock.patch.dict(os.environ, {}, clear=True):
            # WHEN
            result = _find_c4d_detailed_log()
            captured = capsys.readouterr()

            # THEN
            assert result == []
            assert "Neither CONDA_PREFIX nor C4D_DETAILED_LOG_DIR is set" in captured.out

    def test_uses_find_log_file_with_correct_parameters(self):
        """Test that _find_log_file() is used with correct parameters"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "c4d_detailed_logs.txt"
            log_file.write_text("test")

            with mock.patch.dict(os.environ, {"CONDA_PREFIX": tmpdir}):
                with mock.patch(
                    "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._find_log_file",
                    return_value=[str(log_file)],
                ) as mock_find:
                    # WHEN
                    _find_c4d_detailed_log()

                    # THEN
                    mock_find.assert_called_once()
                    call_args = mock_find.call_args[0]
                    assert len(call_args[0]) > 0  # paths list
                    assert "Cinema 4D detailed log" in call_args[1]  # description


class TestGetBugReportSearchPath:
    """Test the _get_bug_report_search_path() function."""

    def test_returns_windows_paths(self):
        """Test that Windows APPDATA/Maxon path with cinema4d_ prefix is returned"""
        # GIVEN
        appdata = r"C:\Users\TestUser\AppData\Roaming"
        with mock.patch("sys.platform", "win32"):
            with mock.patch.dict(os.environ, {"APPDATA": appdata}):
                # WHEN
                base_path, dir_prefix = _get_bug_report_search_path()

                # THEN
                assert base_path == os.path.join(appdata, "Maxon")
                assert dir_prefix == "cinema4d_"

    def test_returns_linux_paths(self):
        """Test that Linux ~/Maxon path with bin_ prefix is returned"""
        # GIVEN
        with mock.patch("sys.platform", "linux"):
            with mock.patch("os.path.expanduser", return_value="/home/user"):
                # WHEN
                base_path, dir_prefix = _get_bug_report_search_path()

                # THEN
                assert base_path == "/home/user/Maxon"
                assert dir_prefix == "bin_"

    def test_handles_missing_appdata(self):
        """Test that missing APPDATA environment variable is handled"""
        # GIVEN
        with mock.patch("sys.platform", "win32"):
            with mock.patch.dict(os.environ, {}, clear=True):
                # WHEN
                base_path, dir_prefix = _get_bug_report_search_path()

                # THEN
                assert base_path == ""
                assert dir_prefix == "cinema4d_"


class TestScanForBugReports:
    """Test the _scan_for_bug_reports() function."""

    def test_finds_bug_reports_in_matching_directories(self):
        """Test that bug reports are found in directories matching prefix"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            bugreports_dir = Path(tmpdir) / "bin_12345" / "_bugreports"
            bugreports_dir.mkdir(parents=True)
            bug_report = bugreports_dir / "_BugReport.txt"
            bug_report.write_text("bug report")

            # WHEN
            result = _scan_for_bug_reports(tmpdir, "bin_")

            # THEN
            assert len(result) == 1
            assert str(bug_report) in result

    def test_ignores_non_matching_directories(self):
        """Test that directories not matching prefix are ignored"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create directory that doesn't match prefix
            other_dir = Path(tmpdir) / "other_12345" / "_bugreports"
            other_dir.mkdir(parents=True)
            bug_report = other_dir / "_BugReport.txt"
            bug_report.write_text("bug report")

            # WHEN
            result = _scan_for_bug_reports(tmpdir, "bin_")

            # THEN
            assert result == []

    def test_ignores_non_bug_report_files(self):
        """Test that only *_BugReport.txt files are included"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            bugreports_dir = Path(tmpdir) / "bin_12345" / "_bugreports"
            bugreports_dir.mkdir(parents=True)
            bug_report = bugreports_dir / "_BugReport.txt"
            other_file = bugreports_dir / "other_file.txt"
            bug_report.write_text("bug report")
            other_file.write_text("other content")

            # WHEN
            result = _scan_for_bug_reports(tmpdir, "bin_")

            # THEN
            assert len(result) == 1
            assert str(bug_report) in result
            assert str(other_file) not in result

    def test_finds_bug_reports_in_multiple_directories(self):
        """Test that bug reports are found in multiple matching directories"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create first directory with bug report
            bugreports_dir1 = Path(tmpdir) / "bin_12345" / "_bugreports"
            bugreports_dir1.mkdir(parents=True)
            bug_report1 = bugreports_dir1 / "_BugReport.txt"
            bug_report1.write_text("bug report 1")

            # Create second directory with bug report
            bugreports_dir2 = Path(tmpdir) / "bin_67890" / "_bugreports"
            bugreports_dir2.mkdir(parents=True)
            bug_report2 = bugreports_dir2 / "_BugReport.txt"
            bug_report2.write_text("bug report 2")

            # WHEN
            result = _scan_for_bug_reports(tmpdir, "bin_")

            # THEN
            assert len(result) == 2
            assert str(bug_report1) in result
            assert str(bug_report2) in result

    def test_handles_exceptions_gracefully(self, capsys):
        """Test that exceptions are caught and logged with error message"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("os.listdir", side_effect=PermissionError("Access denied")):
                # WHEN
                result = _scan_for_bug_reports(tmpdir, "bin_")
                captured = capsys.readouterr()

                # THEN
                assert result == []
                assert "Error scanning for bug reports:" in captured.out


class TestFindBugReports:
    """Test the _find_bug_reports() function."""

    def test_returns_empty_when_base_path_not_set(self):
        """Test that empty list is returned when base_path is empty (guard clause)"""
        # WHEN
        result = _find_bug_reports()

        # Mock to return empty base_path
        with mock.patch(
            "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._get_bug_report_search_path",
            return_value=("", "bin_"),
        ):
            result = _find_bug_reports()

            # THEN
            assert result == []

    def test_returns_empty_when_base_path_not_exists(self):
        """Test that empty list is returned when base_path doesn't exist (guard clause)"""
        # WHEN
        with mock.patch(
            "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._get_bug_report_search_path",
            return_value=("/nonexistent/path", "bin_"),
        ):
            result = _find_bug_reports()

            # THEN
            assert result == []

    def test_delegates_to_scan_function(self, capsys):
        """Test that _scan_for_bug_reports() is called when path exists"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            bugreports_dir = Path(tmpdir) / "bin_12345" / "_bugreports"
            bugreports_dir.mkdir(parents=True)
            bug_report = bugreports_dir / "_BugReport.txt"
            bug_report.write_text("bug report")

            with mock.patch(
                "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._get_bug_report_search_path",
                return_value=(tmpdir, "bin_"),
            ):
                # WHEN
                result = _find_bug_reports()
                captured = capsys.readouterr()

                # THEN
                assert len(result) == 1
                assert str(bug_report) in result
                assert "Checking for bug reports in:" in captured.out

    def test_prints_checking_message(self, capsys):
        """Test that checking message is printed"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._get_bug_report_search_path",
                return_value=(tmpdir, "bin_"),
            ):
                # WHEN
                _find_bug_reports()
                captured = capsys.readouterr()

                # THEN
                assert "Checking for bug reports in:" in captured.out


class TestPrintEnvironmentInfo:
    """Test the _print_environment_info() function."""

    def test_prints_all_environment_variables(self, capsys):
        """Test that all relevant environment variables are printed"""
        # GIVEN
        with mock.patch.dict(
            os.environ,
            {
                "CONDA_PREFIX": "/opt/conda",
                "C4D_DETAILED_LOG_DIR": "/tmp/c4d_logs",
                "HOME": "/home/user",
                "USER": "testuser",
                "REDSHIFT_LOCALDATAPATH": "/custom/redshift",
                "REDSHIFT_COREDATAPATH": "/custom/core",
            },
        ):
            # WHEN
            _print_environment_info()
            captured = capsys.readouterr()

            # THEN
            assert "Environment variables:" in captured.out
            assert "CONDA_PREFIX: /opt/conda" in captured.out
            assert "C4D_DETAILED_LOG_DIR: /tmp/c4d_logs" in captured.out
            assert "HOME: /home/user" in captured.out
            assert "USER: testuser" in captured.out
            assert "REDSHIFT_LOCALDATAPATH: /custom/redshift" in captured.out
            assert "REDSHIFT_COREDATAPATH: /custom/core" in captured.out

    def test_prints_not_set_for_missing_variables(self, capsys):
        """Test that 'NOT SET' is printed for missing variables"""
        # GIVEN
        with mock.patch.dict(os.environ, {}, clear=True):
            # WHEN
            _print_environment_info()
            captured = capsys.readouterr()

            # THEN
            assert "CONDA_PREFIX: NOT SET" in captured.out
            assert "C4D_DETAILED_LOG_DIR: NOT SET" in captured.out
            assert "HOME: NOT SET" in captured.out
            assert "USER: NOT SET" in captured.out
            assert "REDSHIFT_LOCALDATAPATH: NOT SET" in captured.out
            assert "REDSHIFT_COREDATAPATH: NOT SET" in captured.out

    def test_includes_conda_prefix(self, capsys):
        """Test that CONDA_PREFIX is included"""
        # GIVEN
        with mock.patch.dict(os.environ, {"CONDA_PREFIX": "/test/path"}, clear=True):
            # WHEN
            _print_environment_info()
            captured = capsys.readouterr()

            # THEN
            assert "CONDA_PREFIX: /test/path" in captured.out

    def test_includes_redshift_variables(self, capsys):
        """Test that REDSHIFT_* variables are included"""
        # GIVEN
        with mock.patch.dict(
            os.environ,
            {"REDSHIFT_LOCALDATAPATH": "/local/data", "REDSHIFT_COREDATAPATH": "/core/data"},
            clear=True,
        ):
            # WHEN
            _print_environment_info()
            captured = capsys.readouterr()

            # THEN
            assert "REDSHIFT_LOCALDATAPATH: /local/data" in captured.out
            assert "REDSHIFT_COREDATAPATH: /core/data" in captured.out


class TestPrintLogsByType:
    """Test the _print_logs_by_type() function."""

    def test_prints_not_found_message_for_empty_list(self, capsys):
        """Test that not_found_message is printed for empty log list (guard clause)"""
        # WHEN
        _print_logs_by_type([], "TEST LOG", "test logs", "No test logs found")
        captured = capsys.readouterr()

        # THEN
        assert "No test logs found" in captured.out

    def test_prints_count_and_description(self, capsys):
        """Test that count and description are printed when logs are found"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            log_file.write_text("test content")

            # WHEN
            _print_logs_by_type([str(log_file)], "TEST LOG", "test log(s)", "Not found")
            captured = capsys.readouterr()

            # THEN
            assert "Found 1 test log(s)" in captured.out

    def test_calls_print_log_file_for_each_log(self, capsys):
        """Test that print_log_file() is called for each log file"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            log1 = Path(tmpdir) / "test1.log"
            log2 = Path(tmpdir) / "test2.log"
            log1.write_text("content 1")
            log2.write_text("content 2")

            # WHEN
            _print_logs_by_type([str(log1), str(log2)], "TEST LOG", "test logs", "Not found")
            captured = capsys.readouterr()

            # THEN
            assert "TEST LOG:" in captured.out
            assert "content 1" in captured.out
            assert "content 2" in captured.out

    def test_uses_correct_log_type_parameter(self, capsys):
        """Test that correct log_type parameter is used"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            log_file.write_text("test")

            # WHEN
            _print_logs_by_type([str(log_file)], "CUSTOM LOG TYPE", "logs", "Not found")
            captured = capsys.readouterr()

            # THEN
            assert "CUSTOM LOG TYPE:" in captured.out
            assert "END OF CUSTOM LOG TYPE" in captured.out


class TestFindAndPrintRedshiftLogs:
    """Test the _find_and_print_redshift_logs() function."""

    def test_calls_find_redshift_log(self):
        """Test that _find_redshift_log() is called to get log files"""
        # GIVEN
        with mock.patch(
            "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._find_redshift_log",
            return_value=[],
        ) as mock_find:
            # WHEN
            _find_and_print_redshift_logs()

            # THEN
            mock_find.assert_called_once()

    def test_calls_print_logs_by_type_with_correct_params(self, capsys):
        """Test that _print_logs_by_type() is called with correct parameters"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "log.html"
            log_file.write_text("redshift log")

            with mock.patch(
                "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._find_redshift_log",
                return_value=[str(log_file)],
            ):
                # WHEN
                _find_and_print_redshift_logs()
                captured = capsys.readouterr()

                # THEN
                assert "REDSHIFT DEBUG LOG:" in captured.out
                assert "redshift log" in captured.out

    def test_uses_correct_log_type_label(self, capsys):
        """Test that 'REDSHIFT DEBUG LOG' is used as log_type"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "log.html"
            log_file.write_text("test")

            with mock.patch(
                "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._find_redshift_log",
                return_value=[str(log_file)],
            ):
                # WHEN
                _find_and_print_redshift_logs()
                captured = capsys.readouterr()

                # THEN
                assert "REDSHIFT DEBUG LOG:" in captured.out

    def test_uses_appropriate_not_found_message(self, capsys):
        """Test that appropriate not_found_message is used"""
        # GIVEN
        with mock.patch(
            "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._find_redshift_log",
            return_value=[],
        ):
            # WHEN
            _find_and_print_redshift_logs()
            captured = capsys.readouterr()

            # THEN
            assert "No Redshift debug logs (log.html) found" in captured.out


class TestFindAndPrintC4dDetailedLogs:
    """Test the _find_and_print_c4d_detailed_logs() function."""

    def test_calls_find_c4d_detailed_log(self):
        """Test that _find_c4d_detailed_log() is called to get log files"""
        # GIVEN
        with mock.patch(
            "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._find_c4d_detailed_log",
            return_value=[],
        ) as mock_find:
            # WHEN
            _find_and_print_c4d_detailed_logs()

            # THEN
            mock_find.assert_called_once()

    def test_calls_print_logs_by_type_with_correct_params(self, capsys):
        """Test that _print_logs_by_type() is called with correct parameters"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "c4d_detailed_logs.txt"
            log_file.write_text("c4d log")

            with mock.patch(
                "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._find_c4d_detailed_log",
                return_value=[str(log_file)],
            ):
                # WHEN
                _find_and_print_c4d_detailed_logs()
                captured = capsys.readouterr()

                # THEN
                assert "CINEMA 4D DETAILED LOG:" in captured.out
                assert "c4d log" in captured.out

    def test_uses_correct_log_type_label(self, capsys):
        """Test that 'CINEMA 4D DETAILED LOG' is used as log_type"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "c4d_detailed_logs.txt"
            log_file.write_text("test")

            with mock.patch(
                "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._find_c4d_detailed_log",
                return_value=[str(log_file)],
            ):
                # WHEN
                _find_and_print_c4d_detailed_logs()
                captured = capsys.readouterr()

                # THEN
                assert "CINEMA 4D DETAILED LOG:" in captured.out

    def test_uses_appropriate_not_found_message(self, capsys):
        """Test that appropriate not_found_message is used"""
        # GIVEN
        with mock.patch(
            "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._find_c4d_detailed_log",
            return_value=[],
        ):
            # WHEN
            _find_and_print_c4d_detailed_logs()
            captured = capsys.readouterr()

            # THEN
            assert "No Cinema 4D detailed log (c4d_detailed_logs.txt) found" in captured.out


class TestFindAndPrintBugReports:
    """Test the _find_and_print_bug_reports() function."""

    def test_calls_find_bug_reports(self):
        """Test that _find_bug_reports() is called to get bug report files"""
        # GIVEN
        with mock.patch(
            "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._find_bug_reports",
            return_value=[],
        ) as mock_find:
            # WHEN
            _find_and_print_bug_reports()

            # THEN
            mock_find.assert_called_once()

    def test_calls_print_logs_by_type_with_correct_params(self, capsys):
        """Test that _print_logs_by_type() is called with correct parameters"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            bug_report = Path(tmpdir) / "_BugReport.txt"
            bug_report.write_text("bug report")

            with mock.patch(
                "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._find_bug_reports",
                return_value=[str(bug_report)],
            ):
                # WHEN
                _find_and_print_bug_reports()
                captured = capsys.readouterr()

                # THEN
                assert "CINEMA 4D BUG REPORT:" in captured.out
                assert "bug report" in captured.out

    def test_uses_correct_log_type_label(self, capsys):
        """Test that 'CINEMA 4D BUG REPORT' is used as log_type"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            bug_report = Path(tmpdir) / "_BugReport.txt"
            bug_report.write_text("test")

            with mock.patch(
                "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._find_bug_reports",
                return_value=[str(bug_report)],
            ):
                # WHEN
                _find_and_print_bug_reports()
                captured = capsys.readouterr()

                # THEN
                assert "CINEMA 4D BUG REPORT:" in captured.out

    def test_uses_appropriate_not_found_message(self, capsys):
        """Test that appropriate not_found_message is used"""
        # GIVEN
        with mock.patch(
            "deadline.cinema4d_submitter.detailed_logging_scripts.print_logs._find_bug_reports",
            return_value=[],
        ):
            # WHEN
            _find_and_print_bug_reports()
            captured = capsys.readouterr()

            # THEN
            assert "No Cinema 4D bug reports (*_BugReport.txt) found" in captured.out


class TestCleanupEnvironmentVariables:
    """Test the _cleanup_environment_variables() function."""

    def test_prints_unset_commands(self, capsys):
        """Test that openjd_unset_env commands are printed"""
        # WHEN
        _cleanup_environment_variables()
        captured = capsys.readouterr()

        # THEN
        assert "openjd_unset_env: g_alloc" in captured.out
        assert "openjd_unset_env: g_logfile" in captured.out

    def test_prints_confirmation_message(self, capsys):
        """Test that cleanup confirmation message is printed"""
        # WHEN
        _cleanup_environment_variables()
        captured = capsys.readouterr()

        # THEN
        assert "Environment variables cleaned up" in captured.out


class TestCleanupTemporaryDirectory:
    """Test the _cleanup_temporary_directory() function."""

    def test_cleans_up_temp_directory_when_set(self, capsys):
        """Test that temporary directory is removed when C4D_DETAILED_LOG_DIR is set"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_log_dir = os.path.join(tmpdir, "c4d_logs_test")
            os.makedirs(temp_log_dir)

            with mock.patch.dict(os.environ, {"C4D_DETAILED_LOG_DIR": temp_log_dir}):
                # WHEN
                _cleanup_temporary_directory()
                captured = capsys.readouterr()

                # THEN
                assert not os.path.exists(temp_log_dir)
                assert f"Cleaned up temporary directory: {temp_log_dir}" in captured.out

    def test_does_not_fail_when_temp_dir_not_set(self, capsys):
        """Test that cleanup succeeds when C4D_DETAILED_LOG_DIR is not set"""
        # GIVEN
        with mock.patch.dict(os.environ, {}, clear=True):
            # WHEN
            _cleanup_temporary_directory()
            captured = capsys.readouterr()

            # THEN
            # Should not print anything or fail
            assert captured.out == ""

    def test_does_not_fail_when_temp_dir_already_removed(self, capsys):
        """Test that cleanup succeeds when temp directory doesn't exist"""
        # GIVEN
        nonexistent_dir = "/nonexistent/temp/dir"
        with mock.patch.dict(os.environ, {"C4D_DETAILED_LOG_DIR": nonexistent_dir}):
            # WHEN
            _cleanup_temporary_directory()
            captured = capsys.readouterr()

            # THEN
            # Should not print cleanup message for non-existent directory
            assert "Cleaned up temporary directory" not in captured.out

    def test_handles_cleanup_errors_gracefully(self, capsys):
        """Test that cleanup errors are handled gracefully"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_log_dir = os.path.join(tmpdir, "c4d_logs_test")
            os.makedirs(temp_log_dir)

            with mock.patch.dict(os.environ, {"C4D_DETAILED_LOG_DIR": temp_log_dir}):
                with mock.patch("shutil.rmtree", side_effect=PermissionError("Access denied")):
                    # WHEN
                    _cleanup_temporary_directory()
                    captured = capsys.readouterr()

                    # THEN
                    assert "Note: Could not clean up temporary directory" in captured.out
                    assert "Access denied" in captured.out


class TestPrintLogFile:
    """Test the print_log_file() function."""

    def test_prints_log_file_content(self, capsys):
        """Test that log file content is printed correctly"""
        # GIVEN
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as tmp:
            tmp.write("Test log content\nLine 2\nLine 3")
            tmp_path = tmp.name

        try:
            # WHEN
            print_log_file(tmp_path, "TEST LOG")
            captured = capsys.readouterr()

            # THEN
            assert "TEST LOG:" in captured.out
            assert tmp_path in captured.out
            assert "Test log content" in captured.out
            assert "Line 2" in captured.out
            assert "Line 3" in captured.out
            assert "END OF TEST LOG" in captured.out
            assert "=" * 80 in captured.out
        finally:
            os.unlink(tmp_path)

    def test_handles_file_read_error(self, capsys):
        """Test that file read errors are handled gracefully"""
        # GIVEN
        nonexistent_file = "/nonexistent/file.log"

        # WHEN
        print_log_file(nonexistent_file, "ERROR LOG")
        captured = capsys.readouterr()

        # THEN
        assert "ERROR LOG:" in captured.out
        assert "Error reading log file" in captured.out

    def test_handles_unicode_errors(self, capsys):
        """Test that unicode errors are handled with replace strategy"""
        # GIVEN
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".log") as tmp:
            # Write some valid UTF-8 and some invalid bytes
            tmp.write(b"Valid text\n")
            tmp.write(b"\xff\xfe invalid bytes\n")
            tmp.write(b"More valid text")
            tmp_path = tmp.name

        try:
            # WHEN
            print_log_file(tmp_path, "UNICODE LOG")
            captured = capsys.readouterr()

            # THEN
            assert "UNICODE LOG:" in captured.out
            assert "Valid text" in captured.out
            assert "More valid text" in captured.out
        finally:
            os.unlink(tmp_path)

    def test_uses_default_log_type(self, capsys):
        """Test that default log type is used when not specified"""
        # GIVEN
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as tmp:
            tmp.write("Test content")
            tmp_path = tmp.name

        try:
            # WHEN
            print_log_file(tmp_path)
            captured = capsys.readouterr()

            # THEN
            assert "LOG:" in captured.out
            assert "END OF LOG" in captured.out
        finally:
            os.unlink(tmp_path)


class TestPrintDetailedLogs:
    """Test the print_detailed_logs() function."""

    def test_guard_clause_for_disabled(self, capsys):
        """Test that guard clause skips execution when enabled != "1" """
        # WHEN
        print_detailed_logs("0")
        captured = capsys.readouterr()

        # THEN
        assert "Detailed logging is deactivated, skipping log output." in captured.out
        assert "openjd_unset_env" not in captured.out

    def test_complete_workflow_when_enabled(self, capsys):
        """Test that complete workflow executes when enabled == "1" """
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a Redshift log
            log_dir = Path(tmpdir) / "redshiftlocaldata" / "log" / "log.latest.0"
            log_dir.mkdir(parents=True)
            log_file = log_dir / "log.html"
            log_file.write_text("Redshift log content")

            # Create a Cinema 4D detailed log
            c4d_log = Path(tmpdir) / "c4d_detailed_logs.txt"
            c4d_log.write_text("Cinema 4D detailed log content")

            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()

            with mock.patch.dict(os.environ, {"CONDA_PREFIX": tmpdir}):
                with mock.patch("os.path.expanduser", return_value=str(home_dir)):
                    with mock.patch("sys.platform", "linux"):
                        # WHEN
                        print_detailed_logs("1")
                        captured = capsys.readouterr()

                        # THEN
                        assert "Searching for log files..." in captured.out
                        assert "REDSHIFT DEBUG LOG" in captured.out
                        assert "CINEMA 4D DETAILED LOG" in captured.out

    def test_skips_when_deactivated(self, capsys):
        """Test that logging is skipped when deactivated"""
        # WHEN
        print_detailed_logs("0")
        captured = capsys.readouterr()

        # THEN
        assert "Detailed logging is deactivated, skipping log output." in captured.out
        assert "openjd_unset_env" not in captured.out

    def test_prints_logs_when_enabled(self, capsys):
        """Test that logs are printed when enabled"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a Redshift log
            log_dir = Path(tmpdir) / "redshiftlocaldata" / "log" / "log.latest.0"
            log_dir.mkdir(parents=True)
            log_file = log_dir / "log.html"
            log_file.write_text("Redshift log content")

            # Create a Cinema 4D detailed log
            c4d_log = Path(tmpdir) / "c4d_detailed_logs.txt"
            c4d_log.write_text("Cinema 4D detailed log content")

            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()

            with mock.patch.dict(os.environ, {"CONDA_PREFIX": tmpdir}):
                with mock.patch("os.path.expanduser", return_value=str(home_dir)):
                    with mock.patch("sys.platform", "linux"):
                        # WHEN
                        print_detailed_logs("1")
                        captured = capsys.readouterr()

                        # THEN
                        assert "REDSHIFT DEBUG LOG" in captured.out
                        assert "Redshift log content" in captured.out
                        assert "CINEMA 4D DETAILED LOG" in captured.out
                        assert "Cinema 4D detailed log content" in captured.out

    def test_cleans_up_environment_variables_when_enabled(self, capsys):
        """Test that environment variables are cleaned up after printing logs"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()

            with mock.patch.dict(os.environ, {"CONDA_PREFIX": tmpdir}):
                with mock.patch("os.path.expanduser", return_value=str(home_dir)):
                    with mock.patch("sys.platform", "linux"):
                        # WHEN
                        print_detailed_logs("1")
                        captured = capsys.readouterr()

                        # THEN
                        assert "openjd_unset_env: g_alloc" in captured.out
                        assert "openjd_unset_env: g_logfile" in captured.out
                        assert "Environment variables cleaned up" in captured.out

    def test_does_not_clean_up_when_deactivated(self, capsys):
        """Test that environment variables are not cleaned up when logging is deactivated"""
        # WHEN
        print_detailed_logs("0")
        captured = capsys.readouterr()

        # THEN
        assert "openjd_unset_env" not in captured.out
        assert "Environment variables cleaned up" not in captured.out

    def test_prints_no_logs_found_messages(self, capsys):
        """Test that appropriate messages are printed when no logs are found"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()

            with mock.patch.dict(os.environ, {"CONDA_PREFIX": tmpdir}):
                with mock.patch("os.path.expanduser", return_value=str(home_dir)):
                    with mock.patch("sys.platform", "linux"):
                        # WHEN
                        print_detailed_logs("1")
                        captured = capsys.readouterr()

                        # THEN
                        assert "No Redshift debug logs (log.html) found." in captured.out
                        assert (
                            "No Cinema 4D detailed log (c4d_detailed_logs.txt) found."
                            in captured.out
                        )
                        assert "No Cinema 4D bug reports (*_BugReport.txt) found." in captured.out
                        # Still cleans up environment variables
                        assert "openjd_unset_env: g_alloc" in captured.out
                        assert "openjd_unset_env: g_logfile" in captured.out

    def test_prints_bug_reports_when_found(self, capsys):
        """Test that bug reports are printed when found"""
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            maxon_dir = home_dir / "Maxon" / "bin_12345" / "_bugreports"
            maxon_dir.mkdir(parents=True)
            bug_report = maxon_dir / "_BugReport.txt"
            bug_report.write_text("Bug report content")

            with mock.patch.dict(os.environ, {"CONDA_PREFIX": tmpdir}):
                with mock.patch("os.path.expanduser", return_value=str(home_dir)):
                    with mock.patch("sys.platform", "linux"):
                        # WHEN
                        print_detailed_logs("1")
                        captured = capsys.readouterr()

                        # THEN
                        assert "CINEMA 4D BUG REPORT" in captured.out
                        assert "Bug report content" in captured.out
                        # Still cleans up environment variables
                        assert "openjd_unset_env: g_alloc" in captured.out
                        assert "openjd_unset_env: g_logfile" in captured.out
