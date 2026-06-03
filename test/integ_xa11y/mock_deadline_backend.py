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
import re
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

_DEADLINE_API_PREFIX = "/2023-10-12"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            print(f"[mock-deadline] {self.command} {self.path}")



        def _dispatch(self, method: str) -> None:
            path = self.path.split("?", 1)[0]
            for route_method, pattern, handler in routes:
                if route_method != method:
                    continue
                m = pattern.match(path)
                if not m:
                    continue
                status, body = handler(m.groupdict())
                self._send_json(status, body)
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

        def _send_json(self, status: int, body: dict, error_code: str | None = None) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            if error_code:
                self.send_header("x-amzn-errortype", error_code)
            self.end_headers()
            self.wfile.write(payload)

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
    server = HTTPServer(("127.0.0.1", port), handler)
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
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            blob = body + b"&" + self.path.encode("utf-8")
            if b"Action=GetCallerIdentity" in blob:
                self.send_response(200)
                self.send_header("Content-Type", "text/xml")
                self.send_header("Content-Length", str(len(_GET_CALLER_IDENTITY_XML)))
                self.end_headers()
                self.wfile.write(_GET_CALLER_IDENTITY_XML)
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

        def do_POST(self):  # noqa: N802
            self._respond()

        def do_GET(self):  # noqa: N802
            self._respond()

    return _StsHandler


def start_sts_server(port: int = 0):
    """Start the STS mock on 127.0.0.1 in a daemon thread.
    Returns (server, base_url)."""
    server = HTTPServer(("127.0.0.1", port), _make_sts_handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
