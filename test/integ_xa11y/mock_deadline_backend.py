# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Minimal in-process mocks for the AWS APIs the C4D submitter dialog hits
before the user clicks Export bundle. Lets the xa11y integ test run without
a real Deadline Cloud farm or live AWS credentials.

API surface (verified against deadline-cloud's submit_job_to_deadline_dialog
+ shared_job_settings_tab + _queue_parameters at the time of writing):

    sts:GetCallerIdentity        — DeadlineAuthenticationStatus auth probe
    deadline:GetFarm             — DeadlineFarmDisplay.get_item
    deadline:GetQueue            — DeadlineQueueDisplay.get_item
    deadline:ListQueueEnvironments — get_queue_parameter_definitions
                                     (we always return an empty list, which
                                     short-circuits GetQueueEnvironment)

Anything else the dialog calls returns 400 so we fail loudly instead of
quietly waving through an unmocked code path. Future test scenarios that
need more surface (Submit, storage profiles, etc.) should add routes here.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

_DEADLINE_API_PREFIX = "/2023-10-12"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── DIAGNOSTIC INSTRUMENTATION (no behavioural change) ───────────────────────
# Added to investigate the integ-xa11y flake. The mock servers below are plain
# single-threaded HTTPServers, while the submitter dialog fires several Deadline
# API calls concurrently from a 4-thread Qt pool (GetFarm + GetQueue +
# ListQueueEnvironments + GetQueueEnvironment, plus auth-status retriggers). This
# helper timestamps every request and tracks how many are in flight at once, so
# the log shows when requests pile up behind the single server thread and when a
# client gives up on a slow response (BrokenPipeError on the write).
_DIAG_T0 = time.monotonic()
_inflight_lock = threading.Lock()
_inflight = {"deadline": 0, "sts": 0}


def _diag_log(tag: str, msg: str) -> None:
    elapsed = time.monotonic() - _DIAG_T0
    thread = threading.current_thread().name
    # Tag with PID so parent (test) vs child (mock-server subprocess) lines are
    # distinguishable, and a wall-clock time so the two processes' timelines can
    # be lined up against each other (their monotonic clocks differ).
    wall = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{tag} {wall} +{elapsed:7.3f}s pid={os.getpid()} {thread}] {msg}", flush=True)


def _response_latency_s() -> float:
    """Artificial per-response delay (seconds), from MOCK_DEADLINE_LATENCY_S.

    Real Deadline/STS calls take tens-to-hundreds of ms over the network, which
    spaces out the submitter's startup reload retriggers so its queue-parameter
    loads complete one at a time. The in-process mock answers in ~0.1ms, which
    compresses several reload cycles into one tiny window and provokes the
    deadline-cloud queue-parameter reload race. Adding latency here restores the
    real-world spacing. 0 (default) keeps the original instant behaviour.
    """
    try:
        return float(os.environ.get("MOCK_DEADLINE_LATENCY_S", "0") or "0")
    except ValueError:
        return 0.0


_CONDA_QUEUE_ENV_ID = "queueenv-00000000000000000000000000000001"

_CONDA_QUEUE_ENV_TEMPLATE = (
    "specificationRevision: 'jobtemplate-2023-09'\n"
    "environment:\n"
    "  name: Conda\n"
    "parameterDefinitions:\n"
    "- name: CondaPackages\n"
    "  type: STRING\n"
    "  default: cinema4d=2024 cinema4d-openjd\n"
    "  description: >-\n"
    "    Space-separated list of Conda package match specifications.\n"
    "  userInterface:\n"
    "    control: LINE_EDIT\n"
    "    groupLabel: 'Queue Environment: Conda'\n"
    "    label: Conda Packages\n"
    "- name: CondaChannels\n"
    "  type: STRING\n"
    "  default: deadline-cloud\n"
    "  description: >-\n"
    "    Space-separated list of Conda channels.\n"
    "  userInterface:\n"
    "    control: LINE_EDIT\n"
    "    groupLabel: 'Queue Environment: Conda'\n"
    "    label: Conda Channels\n"
)


class MockDeadlineFarm:
    """Holds the seeded farm + queue identifiers and serves the
    Deadline routes the submitter dialog hits at startup."""

    def __init__(
        self,
        farm_id: str = "farm-00000000000000000000000000000000",
        queue_id: str = "queue-00000000000000000000000000000000",
        farm_display_name: str = "Mock Farm",
        queue_display_name: str = "Mock Queue",
    ) -> None:
        self.farm_id = farm_id
        self.queue_id = queue_id
        self._farm = {
            "farmId": farm_id,
            "displayName": farm_display_name,
            "description": "Mock farm for xa11y integ test",
            "kmsKeyArn": "",
            "createdAt": _now_iso(),
            "createdBy": "mock-user",
        }
        self._queue = {
            "queueId": queue_id,
            "farmId": farm_id,
            "displayName": queue_display_name,
            "description": "Mock queue for xa11y integ test",
            "status": "ACTIVE",
            "defaultBudgetAction": "NONE",
            "createdAt": _now_iso(),
            "createdBy": "mock-user",
        }

    # Each handler returns (status, body_dict). 404 if IDs don't match.

    def get_farm(self, path_params: dict) -> tuple[int, dict]:
        if path_params["farmId"] != self.farm_id:
            return 404, {"message": f"Farm {path_params['farmId']} not found"}
        return 200, dict(self._farm)

    def get_queue(self, path_params: dict) -> tuple[int, dict]:
        if (
            path_params["farmId"] != self.farm_id
            or path_params["queueId"] != self.queue_id
        ):
            return 404, {"message": f"Queue {path_params.get('queueId')} not found"}
        return 200, dict(self._queue)

    def list_farms(self, path_params: dict) -> tuple[int, dict]:
        return 200, {
            "farms": [
                {
                    "farmId": self.farm_id,
                    "displayName": self._farm["displayName"],
                    "createdAt": self._farm["createdAt"],
                    "createdBy": self._farm["createdBy"],
                }
            ]
        }

    def list_queues(self, path_params: dict) -> tuple[int, dict]:
        if path_params["farmId"] != self.farm_id:
            return 404, {"message": f"Farm {path_params['farmId']} not found"}
        return 200, {
            "queues": [
                {
                    "queueId": self.queue_id,
                    "farmId": self.farm_id,
                    "displayName": self._queue["displayName"],
                    "status": "ACTIVE",
                    "createdAt": self._queue["createdAt"],
                    "createdBy": self._queue["createdBy"],
                }
            ]
        }

    def list_queue_environments(self, path_params: dict) -> tuple[int, dict]:
        if (
            path_params["farmId"] != self.farm_id
            or path_params["queueId"] != self.queue_id
        ):
            return 404, {"message": f"Queue {path_params.get('queueId')} not found"}
        return 200, {
            "environments": [
                {
                    "queueEnvironmentId": _CONDA_QUEUE_ENV_ID,
                    "name": "Conda",
                    "priority": 1,
                }
            ]
        }

    def get_queue_environment(self, path_params: dict) -> tuple[int, dict]:
        if (
            path_params["farmId"] != self.farm_id
            or path_params["queueId"] != self.queue_id
        ):
            return 404, {"message": f"Queue {path_params.get('queueId')} not found"}
        if path_params["queueEnvironmentId"] != _CONDA_QUEUE_ENV_ID:
            return 404, {
                "message": f"QueueEnvironment {path_params['queueEnvironmentId']} not found"
            }
        return 200, {
            "queueEnvironmentId": _CONDA_QUEUE_ENV_ID,
            "name": "Conda",
            "priority": 1,
            "template": _CONDA_QUEUE_ENV_TEMPLATE,
            "templateType": "YAML",
            "createdAt": _now_iso(),
            "createdBy": "mock-user",
        }


def _compile_route(method: str, path: str, handler):
    pattern = re.compile(
        "^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", _DEADLINE_API_PREFIX + path) + "$"
    )
    return method, pattern, handler


def _make_deadline_handler(farm: MockDeadlineFarm):
    routes = [
        _compile_route("GET", "/farms", farm.list_farms),
        _compile_route("GET", "/farms/{farmId}", farm.get_farm),
        _compile_route("GET", "/farms/{farmId}/queues", farm.list_queues),
        _compile_route("GET", "/farms/{farmId}/queues/{queueId}", farm.get_queue),
        _compile_route(
            "GET",
            "/farms/{farmId}/queues/{queueId}/environments",
            farm.list_queue_environments,
        ),
        _compile_route(
            "GET",
            "/farms/{farmId}/queues/{queueId}/environments/{queueEnvironmentId}",
            farm.get_queue_environment,
        ),
    ]

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # flush so this interleaves correctly with the flushed _diag_log lines
            print(f"[mock-deadline] {self.command} {self.path}", flush=True)

        def _dispatch(self, method: str) -> None:
            path = self.path.split("?", 1)[0]

            # DIAGNOSTIC: record arrival + concurrent in-flight count. Because
            # this server is single-threaded, a second request can't actually be
            # *served* until the first returns; the count reflects how many the
            # client fired while an earlier one was still being handled.
            with _inflight_lock:
                _inflight["deadline"] += 1
                concurrent = _inflight["deadline"]
            started = time.monotonic()
            _diag_log(
                "mock-deadline",
                f"--> {method} {path} (in-flight now: {concurrent})",
            )

            # Simulate real-network latency so the submitter's startup reload
            # retriggers are spaced out instead of cancel-storming the in-flight
            # queue-parameter load (see _response_latency_s).
            latency = _response_latency_s()
            if latency:
                time.sleep(latency)

            try:
                for route_method, pattern, handler in routes:
                    if route_method != method:
                        continue
                    m = pattern.match(path)
                    if not m:
                        continue
                    status, body = handler(m.groupdict())
                    self._send_json(status, body)
                    _diag_log(
                        "mock-deadline",
                        f"<-- {method} {path} {status} "
                        f"({(time.monotonic() - started) * 1000:.1f}ms)",
                    )
                    return
                self._send_json(
                    400,
                    {
                        "message": (
                            f"Mock Deadline backend has no route for {method} {path}. "
                            f"If the submitter started calling a new API, add it to "
                            f"MockDeadlineFarm."
                        )
                    },
                    error_code="ValidationException",
                )
                _diag_log("mock-deadline", f"<-- {method} {path} 400 NO ROUTE")
            finally:
                with _inflight_lock:
                    _inflight["deadline"] -= 1

        def _send_json(self, status: int, body: dict, error_code: str | None = None) -> None:
            payload = json.dumps(body).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                if error_code:
                    self.send_header("x-amzn-errortype", error_code)
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError) as e:
                # DIAGNOSTIC: the client (C4D's botocore) closed the socket before
                # we finished responding -- i.e. it timed out / gave up waiting on
                # this single-threaded server. This is the smoking gun for the
                # flake: a queue-environment call that never gets its answer.
                _diag_log(
                    "mock-deadline",
                    f"!! CLIENT DISCONNECTED before response sent for "
                    f"{self.command} {self.path}: {e!r}",
                )

        def do_GET(self):  # noqa: N802
            self._dispatch("GET")

        def do_POST(self):  # noqa: N802
            self._dispatch("POST")

    return _Handler


def start_deadline_server(farm: MockDeadlineFarm, port: int = 0):
    """Start the Deadline mock on 127.0.0.1 in a daemon thread.

    Returns (server, base_url). Caller is responsible for shutdown(); the
    integ_xa11y conftest does this in the fixture's finally block.

    Note: callers must also disable botocore's `management.` host-prefix
    injection (the xa11y conftest installs a sitecustomize.py shim for
    Cinema 4D's bundled Python).
    """
    handler = _make_deadline_handler(farm)
    # EXPERIMENT: ThreadingHTTPServer so each request gets its own thread, in
    # case the single-threaded server's head-of-line blocking is what stalls
    # queue-environment loading. The heartbeat thread (see start_heartbeat)
    # will tell us whether these request threads actually get to RUN, or whether
    # they're starved of the GIL while the main thread sits in xa11y's native
    # waits.
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


# ========== STS Mock ==========
#
# DeadlineAuthenticationStatus.refresh_status() calls sts:GetCallerIdentity
# to decide whether the API is reachable. The dialog's "AWS Deadline Cloud
# API is not accessible" warning blocks Submit (not Export bundle) but the
# auth widget still surfaces the error, which can confuse the test. Always
# return a successful identity. STS uses XML query protocol, not JSON.

_GET_CALLER_IDENTITY_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<GetCallerIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">\n'
    "  <GetCallerIdentityResult>\n"
    "    <Arn>arn:aws:iam::000000000000:user/MockDeadlineUser</Arn>\n"
    "    <UserId>AIDAMOCKMOCKMOCKMOCK</UserId>\n"
    "    <Account>000000000000</Account>\n"
    "  </GetCallerIdentityResult>\n"
    "  <ResponseMetadata>\n"
    "    <RequestId>00000000-0000-0000-0000-000000000000</RequestId>\n"
    "  </ResponseMetadata>\n"
    "</GetCallerIdentityResponse>\n"
).encode("utf-8")


def _make_sts_handler():
    class _StsHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def _respond(self) -> None:
            # DIAGNOSTIC: STS auth probes share the same single-threaded-server
            # contention story as Deadline; log them so the timeline lines up.
            with _inflight_lock:
                _inflight["sts"] += 1
                concurrent = _inflight["sts"]
            started = time.monotonic()
            _diag_log("mock-sts", f"--> {self.command} {self.path} (in-flight now: {concurrent})")
            latency = _response_latency_s()
            if latency:
                time.sleep(latency)
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""
                blob = body + b"&" + self.path.encode("utf-8")
                if b"Action=GetCallerIdentity" in blob:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/xml")
                    self.send_header("Content-Length", str(len(_GET_CALLER_IDENTITY_XML)))
                    self.end_headers()
                    self.wfile.write(_GET_CALLER_IDENTITY_XML)
                    _diag_log(
                        "mock-sts",
                        f"<-- GetCallerIdentity 200 "
                        f"({(time.monotonic() - started) * 1000:.1f}ms)",
                    )
                    return
                msg = (
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    "<ErrorResponse><Error>"
                    "<Code>InvalidAction</Code>"
                    "<Message>Mock STS only implements GetCallerIdentity</Message>"
                    "</Error></ErrorResponse>\n"
                ).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "text/xml")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
            except (BrokenPipeError, ConnectionResetError) as e:
                _diag_log(
                    "mock-sts",
                    f"!! CLIENT DISCONNECTED before response sent: {e!r}",
                )
            finally:
                with _inflight_lock:
                    _inflight["sts"] -= 1

        def do_POST(self):  # noqa: N802
            self._respond()

        def do_GET(self):  # noqa: N802
            self._respond()

    return _StsHandler


def start_sts_server(port: int = 0):
    """Start the STS mock on 127.0.0.1 in a daemon thread.
    Returns (server, base_url)."""
    # EXPERIMENT: ThreadingHTTPServer, same rationale as start_deadline_server.
    server = ThreadingHTTPServer(("127.0.0.1", port), _make_sts_handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


# ── HEARTBEAT PROBE (diagnostic) ─────────────────────────────────────────────
# The key question the ThreadingHTTPServer experiment must answer: do background
# Python threads in the pytest PARENT process actually get scheduled while the
# main thread is parked inside xa11y's native wait_* calls? If xa11y's native
# extension holds the GIL during its polling, then NO Python thread (not the
# server thread, not request threads, not this heartbeat) can run -- and
# switching to ThreadingHTTPServer changes nothing, because the new request
# threads still can't acquire the GIL.
#
# This heartbeat ticks every 0.5s on its own daemon thread and logs the actual
# wall-clock gap between ticks. A gap of ~0.5s means Python threads run freely
# (so threading the server WILL help). A multi-second gap that lines up with an
# xa11y wait is direct proof the GIL is starved and the server change is moot.
def start_heartbeat(interval_s: float = 0.5):
    """Start a daemon thread that logs inter-tick latency. Returns a stop fn."""
    stop = threading.Event()

    def _beat():
        last = time.monotonic()
        while not stop.is_set():
            stop.wait(interval_s)
            now = time.monotonic()
            gap = now - last
            last = now
            # Only shout when the gap is meaningfully larger than the interval,
            # which is the interesting (thread-starved) case.
            if gap > interval_s * 2:
                _diag_log(
                    "heartbeat",
                    f"!! parent-process Python threads STARVED for {gap:.2f}s "
                    f"(expected ~{interval_s:.2f}s) -- GIL likely held by a "
                    f"native xa11y wait; server threading can't help here",
                )
            else:
                _diag_log("heartbeat", f"tick (gap {gap:.2f}s)")

    threading.Thread(target=_beat, daemon=True, name="diag-heartbeat").start()
    return stop.set


# ── OUT-OF-PROCESS MOCK SERVERS (experiment: GIL decoupling) ─────────────────
# The heartbeat proved that while the test's main thread sits in xa11y's native
# wait_* calls, the GIL is held and NO Python thread in the pytest process runs
# -- so the in-process mock servers (threaded or not) can't answer the
# submitter's API calls until xa11y briefly yields. That's the flake.
#
# This launcher runs the mock servers in a SEPARATE PROCESS. A different process
# has its own interpreter and its own GIL, so it keeps answering requests no
# matter what xa11y is doing in the parent. If this fixes the flake, the root
# cause is confirmed as in-process GIL starvation (not server concurrency).
#
# Protocol: the parent spawns `python -m <thismodule> --serve <handshake>`. The
# child stands up both servers, writes their URLs as JSON to <handshake>, then
# serves forever until terminated. The child inherits the parent's stdout, so
# its diagnostic request logs still appear in the test output (tagged with its
# own pid via _diag_log).


class _SubprocessServers:
    """Handle for the out-of-process mock servers. Mimics enough of the
    in-process (server, url) shape that the conftest teardown can call
    .shutdown()/.server_close() on each without caring which mode is active."""

    def __init__(self, proc: subprocess.Popen, deadline_url: str, sts_url: str):
        self._proc = proc
        self.deadline_url = deadline_url
        self.sts_url = sts_url

    def shutdown(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)

    def server_close(self) -> None:
        # No-op: the child owns the sockets and closes them when it exits.
        pass


def start_mock_servers_subprocess(farm: MockDeadlineFarm, timeout_s: float = 30.0):
    """Launch both mock servers in a separate process so they are immune to the
    parent's GIL being held by xa11y native waits.

    Returns (handle, deadline_url, sts_url) where handle has shutdown()/
    server_close() methods matching the in-process servers' teardown contract.
    """
    handshake = tempfile.NamedTemporaryFile(
        prefix="c4d-mock-handshake-", suffix=".json", delete=False
    )
    handshake.close()
    handshake_path = handshake.name

    # Pass the farm identity to the child so it serves the same IDs the parent
    # seeded into the deadline config. The defaults match MockDeadlineFarm, but
    # pass them explicitly so this stays correct if the fixture customises them.
    cmd = [
        sys.executable,
        os.path.abspath(__file__),
        "--serve",
        "--handshake",
        handshake_path,
        "--farm-id",
        farm.farm_id,
        "--queue-id",
        farm.queue_id,
    ]
    _diag_log("mock-launcher", f"spawning out-of-process mock servers: {cmd}")
    proc = subprocess.Popen(cmd)

    # Wait for the child to publish its URLs.
    deadline_t = time.monotonic() + timeout_s
    urls = None
    while time.monotonic() < deadline_t:
        if proc.poll() is not None:
            raise RuntimeError(
                f"mock server subprocess exited early (rc={proc.returncode}) "
                f"before publishing URLs"
            )
        try:
            with open(handshake_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                urls = json.loads(content)
                break
        except (json.JSONDecodeError, FileNotFoundError):
            pass
        time.sleep(0.1)

    try:
        os.unlink(handshake_path)
    except OSError:
        pass

    if urls is None:
        proc.terminate()
        raise RuntimeError("mock server subprocess did not publish URLs in time")

    _diag_log(
        "mock-launcher",
        f"mock servers up in pid={proc.pid}: deadline={urls['deadline']} sts={urls['sts']}",
    )
    handle = _SubprocessServers(proc, urls["deadline"], urls["sts"])
    return handle, urls["deadline"], urls["sts"]


def _serve_main(argv: list[str]) -> None:
    """Entry point for the mock-server subprocess. Stands up both servers, writes
    their URLs to the handshake file, and serves forever until terminated."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--handshake", required=True)
    parser.add_argument("--farm-id", required=True)
    parser.add_argument("--queue-id", required=True)
    args = parser.parse_args(argv)

    farm = MockDeadlineFarm(farm_id=args.farm_id, queue_id=args.queue_id)
    deadline_server, deadline_url = start_deadline_server(farm)
    sts_server, sts_url = start_sts_server()

    _diag_log(
        "mock-child",
        f"serving deadline={deadline_url} sts={sts_url}; writing handshake",
    )
    # Write atomically so the parent never reads a half-written file.
    tmp = args.handshake + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"deadline": deadline_url, "sts": sts_url}, f)
    os.replace(tmp, args.handshake)

    # Serve until the parent terminates us.
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    if "--serve" in sys.argv[1:]:
        _serve_main(sys.argv[1:])
