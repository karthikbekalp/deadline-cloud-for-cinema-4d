# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Helpers to point the Cinema 4D submitter subprocess at the mock backend.

The submitter runs inside the C4D subprocess, so it can only be redirected to
the mock through process configuration: environment variables (endpoint
override + dummy credentials + telemetry opt-out + isolated config/home) and a
deadline config file naming the mock's farm/queue. This module builds both, so
the conftest fixture stays small.

The complementary half lives in ``fixtures/auto_open_submitter/AutoOpenSubmitter.pyp``:
when ``DEADLINE_CLOUD_MOCK_MODE=1`` it patches ``socket.getaddrinfo`` so
botocore's ``management.``-prefixed Deadline host resolves to ``127.0.0.1``.
"""

from __future__ import annotations

from pathlib import Path

# Dummy static credentials. They only need to satisfy botocore's signing; the
# mock never checks them. ``(default)`` profile -> default cred chain -> these.
MOCK_ACCESS_KEY = "testing"
MOCK_SECRET_KEY = "testing"
MOCK_SESSION_TOKEN = "testing"
MOCK_REGION = "us-west-2"


def write_deadline_config(
    config_path: Path, *, farm_id: str, queue_id: str, job_history_dir: Path
) -> None:
    """Write a minimal deadline config selecting the mock's farm/queue.

    Format matches what deadline-cloud's own ``set_setting`` produces (verified
    empirically); we write it directly rather than calling ``set_setting`` so we
    don't mutate the deadline config module's global cached path/state inside the
    pytest process. ``DEADLINE_CONFIG_FILE_PATH`` (set in :func:`build_mock_env`)
    points the submitter at this file.
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "[profile-(default) defaults]\n"
        f"farm_id = {farm_id}\n"
        "\n"
        f"[profile-(default) {farm_id} defaults]\n"
        f"queue_id = {queue_id}\n"
        "\n"
        "[profile-(default) settings]\n"
        f"job_history_dir = {job_history_dir}\n"
        "\n"
        # Suppress the submitter's "update available" dialog: it would pop up
        # over the submitter on open and steal focus / confuse the xa11y dialog
        # search. Defaults to "true" in deadline-cloud, so we must opt out here.
        # NOTE: this setting resolves to the bare [settings] section, NOT the
        # profile-prefixed one that job_history_dir uses -- putting it under
        # [profile-(default) settings] is silently ignored.
        "[settings]\n"
        "submitter_update_notification = false\n"
        "\n"
        "[telemetry]\n"
        "opt_out = true\n",
        encoding="utf-8",
    )


def build_mock_env(
    base_env: dict,
    *,
    deadline_endpoint_url: str,
    config_path: Path,
    home_dir: Path,
) -> dict:
    """Return ``base_env`` overlaid with everything needed to redirect the C4D
    submitter subprocess to the mock Deadline backend.

    * ``DEADLINE_CLOUD_MOCK_MODE`` -- switches on the sidecar's ``management.``
      getaddrinfo redirect.
    * ``AWS_ENDPOINT_URL_DEADLINE`` -- routes the deadline client to the mock.
    * dummy AWS creds + region -- satisfy botocore signing without real AWS.
    * ``DEADLINE_CONFIG_FILE_PATH`` -- the temp config naming the mock farm/queue.
    * ``DEADLINE_CLOUD_TELEMETRY_OPT_OUT`` -- belt-and-suspenders with the config
      setting; guarantees the telemetry thread (the only STS caller) never runs.
    * ``HOME`` / ``USERPROFILE`` -- isolate from the developer's real
      ``~/.deadline`` and AWS config so the test is hermetic.
    """
    home_dir.mkdir(parents=True, exist_ok=True)
    return {
        **base_env,
        "DEADLINE_CLOUD_MOCK_MODE": "1",
        "AWS_ENDPOINT_URL_DEADLINE": deadline_endpoint_url,
        "AWS_ACCESS_KEY_ID": MOCK_ACCESS_KEY,
        "AWS_SECRET_ACCESS_KEY": MOCK_SECRET_KEY,
        "AWS_SESSION_TOKEN": MOCK_SESSION_TOKEN,
        "AWS_DEFAULT_REGION": MOCK_REGION,
        "AWS_REGION": MOCK_REGION,
        "DEADLINE_CONFIG_FILE_PATH": str(config_path),
        "DEADLINE_CLOUD_TELEMETRY_OPT_OUT": "true",
        "HOME": str(home_dir),
        "USERPROFILE": str(home_dir),
    }
