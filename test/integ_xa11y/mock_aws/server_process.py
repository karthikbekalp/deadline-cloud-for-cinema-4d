# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Run the mock Deadline backend in a separate process.

Running the server in its own process gives it an independent GIL.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

from . import fixtures_data as data
from .deadline import _ADMIN_CALLS_PATH

_SERVER_SCRIPT = Path(__file__).parent / "_run_server.py"


class RemoteBackend:
    """Test-side view of the out-of-process backend."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.farm_id = data.FARM_ID
        self.queue_id = data.QUEUE_ID

    def _fetch(self) -> dict:
        url = f"{self.base_url}{_ADMIN_CALLS_PATH}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode())

    @property
    def call_counts(self) -> dict:
        return self._fetch()["call_counts"]

    @property
    def request_log(self) -> list:
        return [tuple(r) for r in self._fetch()["request_log"]]

    @property
    def unmatched_requests(self) -> list:
        return [tuple(r) for r in self._fetch()["unmatched_requests"]]


class MockServerProcess:
    """Handle for a mock Deadline server running in a child process."""

    def __init__(self, response_delay_s: float = 0.3):
        self._response_delay_s = response_delay_s
        self._proc: Optional[subprocess.Popen] = None
        self.base_url: Optional[str] = None
        self.backend: Optional[RemoteBackend] = None

    def start(self) -> "MockServerProcess":
        self._proc = subprocess.Popen(
            [sys.executable, str(_SERVER_SCRIPT), str(self._response_delay_s)],
            stdout=subprocess.PIPE,
            stderr=None,
        )
        # The child prints its base_url on stdout once ready.
        # NOTE: This readline() has no timeout. Attempts to add one (via
        # threading.Thread + join(timeout)) caused macOS GitHub runners to hang.
        assert self._proc.stdout is not None
        line = self._proc.stdout.readline().decode().strip()
        if not line or not line.startswith("http"):
            rc = self._proc.poll()
            raise RuntimeError(f"Mock server failed to start (got: {line!r}, exitcode={rc})")
        self.base_url = line
        self.backend = RemoteBackend(self.base_url)
        self._wait_ready()
        return self

    def _wait_ready(self, timeout: float = 10.0) -> None:
        assert self.backend is not None
        deadline_t = time.monotonic() + timeout
        last_err: Optional[Exception] = None
        while time.monotonic() < deadline_t:
            try:
                self.backend._fetch()
                return
            except Exception as e:
                last_err = e
                time.sleep(0.1)
        raise RuntimeError(f"mock server did not become ready: {last_err!r}")

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        self._proc = None

    def __enter__(self) -> "MockServerProcess":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
