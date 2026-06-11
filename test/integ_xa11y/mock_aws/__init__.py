# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Hand-rolled, in-process mock AWS servers for the Cinema 4D submitter integ test.

This package lets the xa11y-driven submitter test run fully offline: instead of
talking to the real Deadline Cloud service with the machine's ambient AWS
credentials, the Cinema 4D subprocess is pointed at a local HTTP server via the
``AWS_ENDPOINT_URL_DEADLINE`` environment variable (plus dummy credentials).

The Deadline backend speaks the rest-json protocol the real ``deadline`` client
expects, implementing just the operations the Export-bundle dialog calls. It
binds to ``127.0.0.1`` on an ephemeral port and runs in a separate process (see
``server_process.py`` for why a process rather than a thread).
"""

from .deadline import MockDeadlineBackend, start_server

__all__ = ["MockDeadlineBackend", "start_server"]
