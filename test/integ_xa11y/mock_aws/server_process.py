# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Run the mock Deadline backend in a separate process.

Why a separate process (not a thread)
--------------------------------------
The xa11y accessibility library is a native extension (``_native.abi3.so``)
whose ``wait_visible`` / ``wait_hidden`` poll loops hold the CPython GIL for the
large majority of their duration (measured: ~13 background-thread ticks during a
6.4s wait, vs ~64 expected if the GIL were free). The submitter integ test calls
``wait_hidden(timeout=60s)`` while the queue environments load.

If the mock server runs as a daemon *thread* in the pytest process, that 60s
native wait starves the server thread: it can barely accept connections, so the
Cinema 4D subprocess's HTTP calls pile up past the listen backlog and time out,
the queue-env load never completes, the "Loading Queue Environments..." caption
never clears, and the wait rides its full 60s. (Tell-tale sign: the server logs
a served request the instant ``wait_hidden`` returns.)

Running the server in its own process gives it an independent GIL, so it keeps
serving at full speed no matter what xa11y does on the test side.

Observability across the process boundary
------------------------------------------
``call_counts`` / ``request_log`` / ``unmatched_requests`` live in the child
process now, so the test can't read the backend object directly. The server
exposes them at ``GET /__admin__/calls``; :class:`RemoteBackend` fetches that
endpoint on attribute access, so existing assertions
(``backend.call_counts``, ``backend.unmatched_requests``) keep working.
"""

from __future__ import annotations

import json
import multiprocessing
import time
import urllib.request
from typing import Optional

from . import fixtures_data as data
from .deadline import _ADMIN_CALLS_PATH


def _serve(response_delay_s: float, port_queue) -> None:
    """Child-process entrypoint: start the server, report the port, serve forever."""
    import traceback
    import sys

    try:
        print("[mock-server-child] starting imports...", file=sys.stderr, flush=True)
        from .deadline import MockDeadlineBackend, start_server

        print("[mock-server-child] imports done, creating backend...", file=sys.stderr, flush=True)
        backend = MockDeadlineBackend(response_delay_s=response_delay_s)
        backend.log_callback = lambda msg: print(f"[mock-deadline] {msg}", flush=True)
        print("[mock-server-child] starting server...", file=sys.stderr, flush=True)
        server, base_url, _thread = start_server(backend)
        print(f"[mock-server-child] server at {base_url}", file=sys.stderr, flush=True)
        port_queue.put(base_url)
        server.serve_forever()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        port_queue.put(f"ERROR: {traceback.format_exc()}")
        sys.exit(1)


class RemoteBackend:
    """Test-side view of the out-of-process backend.

    Exposes the same attributes the in-process backend did -- ``farm_id``,
    ``queue_id``, ``call_counts``, ``request_log``, ``unmatched_requests`` --
    but the observability fields are fetched live from the server's admin
    endpoint each time they're read.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url
        # Static identifiers mirror the seeded fixtures, so the test can write a
        # matching deadline config without round-tripping to the server.
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
    """Handle for a mock Deadline server running in a child process.

    Use as a context manager. ``base_url`` is the endpoint to point
    ``AWS_ENDPOINT_URL_DEADLINE`` at; ``backend`` is a :class:`RemoteBackend`
    for assertions.
    """

    def __init__(self, response_delay_s: float = 0.3):
        self._response_delay_s = response_delay_s
        # spawn context yields a SpawnProcess; BaseProcess is the common base.
        self._proc: Optional[multiprocessing.process.BaseProcess] = None
        self.base_url: Optional[str] = None
        self.backend: Optional[RemoteBackend] = None

    def start(self) -> "MockServerProcess":
        # 'spawn' so the child is a clean interpreter (no inherited C4D/Qt/xa11y
        # state, no fork-after-threads hazards) on every platform.
        # Exception: when running inside a pytest-xdist worker, __main__ is
        # <stdin> which 'spawn' can't re-import. Fall back to 'fork' on
        # macOS/Linux in that case (safe here — no Qt/xa11y loaded yet in fixture
        # setup). On Windows, 'fork' doesn't exist so 'spawn' is the only option
        # (and it works there because xdist uses a different worker bootstrap).
        import os
        import sys

        method = os.environ.get("MULTIPROCESSING_START_METHOD", "")
        if not method:
            in_xdist = "PYTEST_XDIST_WORKER" in os.environ
            if in_xdist and sys.platform != "win32":
                method = "fork"
            else:
                method = "spawn"
        ctx = multiprocessing.get_context(method)
        port_queue = ctx.Queue()
        self._proc = ctx.Process(
            target=_serve,
            args=(self._response_delay_s, port_queue),
            daemon=True,
        )
        self._proc.start()
        # Wait for the child to bind and report its URL.
        import sys

        print(f"[MockServerProcess] child started (pid={self._proc.pid}, method={method})", flush=True)
        try:
            self.base_url = port_queue.get(timeout=30)
        except Exception:
            alive = self._proc.is_alive()
            print(
                f"[MockServerProcess] timeout! child alive={alive}, exitcode={self._proc.exitcode}",
                file=sys.stderr,
                flush=True,
            )
            raise
        if self.base_url and self.base_url.startswith("ERROR:"):
            raise RuntimeError(f"Mock server child failed: {self.base_url}")
        self.backend = RemoteBackend(self.base_url)
        self._wait_ready()
        return self

    def _wait_ready(self, timeout: float = 10.0) -> None:
        """Block until the admin endpoint answers, so the test never races the
        server's startup."""
        deadline_t = time.monotonic() + timeout
        last_err: Optional[Exception] = None
        while time.monotonic() < deadline_t:
            try:
                self.backend._fetch()  # type: ignore[union-attr]
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(0.1)
        raise RuntimeError(f"mock server did not become ready: {last_err!r}")

    def stop(self) -> None:
        if self._proc is not None and self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(timeout=5)
        self._proc = None

    def __enter__(self) -> "MockServerProcess":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
