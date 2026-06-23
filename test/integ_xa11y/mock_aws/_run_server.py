#!/usr/bin/env python3
"""Standalone script to run the mock Deadline backend server.

Launched by MockServerProcess via subprocess.Popen. Prints the base_url to
stdout once the server is ready, then serves until terminated.
"""

import sys
from pathlib import Path

# Add the repo root so both 'src' and 'test' packages are importable.
_repo_root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_repo_root / "src"))
sys.path.insert(0, str(_repo_root / "test" / "integ_xa11y"))

from mock_aws.deadline import MockDeadlineBackend, start_server


def main():
    response_delay_s = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3

    backend = MockDeadlineBackend(response_delay_s=response_delay_s)
    backend.log_callback = lambda msg: print(f"[mock-deadline] {msg}", file=sys.stderr, flush=True)
    server, base_url, _thread = start_server(backend)

    # Signal the parent that we're ready.
    print(base_url, flush=True)

    # Serve until killed.
    server.serve_forever()


if __name__ == "__main__":
    main()
