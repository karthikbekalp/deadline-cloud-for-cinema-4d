### What was the problem/requirement? (What/Why)

The Windows integration workflow exposed two startup failure modes:

1. Cinema 4D 2025 encountered a rare native startup crash and exited with
   `0xC0000005` (`STATUS_ACCESS_VIOLATION`) before its submitter accessibility
   application appeared. The test continued waiting for UI Automation, which
   obscured the native process failure.
2. A later run never opened the local SSM license-forwarding port. The workflow
   did not retain the AWS CLI process or capture its stderr, so it could only
   report a port timeout. `Test-NetConnection` also made the nominal timeout
   substantially longer than the message indicated.

Failed jobs:

- Cinema 4D startup crash:
  https://github.com/aws-deadline/deadline-cloud-for-cinema-4d/actions/runs/31621623631/job/94197613785
- SSM port-forward startup failure:
  https://github.com/aws-deadline/deadline-cloud-for-cinema-4d/actions/runs/31669886824/job/94352428414

### What was the solution? (How)

The Windows integration test now monitors the launched Cinema 4D process before
each UI Automation scan:

- If the accessibility application appears, the test continues normally.
- If Cinema 4D exits first, the test reports its decimal and hexadecimal exit
  codes and restarts Cinema 4D once.
- The failed process is cleaned up before the second launch.
- Each attempt logs its PID and has a separate plugin diagnostic log.
- A warning records the first startup failure even when the second launch
  succeeds.
- If the second launch also exits early, the test fails with the native exit
  code.

Only an early process exit is retried. Accessibility timeouts and failures after
startup are not retried.

The integration tests now run in-process with uncaptured output so Cinema 4D
and xa11y progress is visible immediately. If a test runs for ten minutes,
pytest's faulthandler dumps every Python thread and exits rather than waiting
for the GitHub Actions job timeout.

The Windows SSM setup now:

- Retains the `aws ssm start-session` process and reports an early exit code.
- Uses a direct TCP connection to check the local listener six times at
  five-second intervals.
- If the first session does not open the port, cleans up the partial process and
  session, waits five seconds, and starts one fresh SSM session.
- After both attempts fail, reports whether the AWS CLI exited without printing
  raw SSM logs.
- Captures the SSM session ID for deterministic teardown.

### What is the impact of this change?

This change only affects the integration test harness and Windows integration
workflow. It makes the suite resilient to a rare, transient Cinema 4D startup
crash, retries a failed SSM tunnel once, and reports whether the AWS CLI exited
if both tunnel attempts fail.

There is no change to the Cinema 4D submitter, adaptor, customer workflows, or
production behavior.

### How was this change tested?

- Unit tests: `358 passed, 6 skipped`
- `hatch run lint`: passed
- Workflow YAML parsing: passed
- `git diff --check`: passed

- Have you run the unit tests?

  Yes. `hatch run test` completed with `358 passed, 6 skipped`.

- Have you run the integration tests? (Add your integration test report below)

  Not locally. The full integration suite requires a Windows environment with
  Cinema 4D installed, GitHub OIDC credentials, and access to the license
  infrastructure. End-to-end validation must run in the versioned Windows
  integration workflow.

- Have you made changes to the submitter?

  No. The changes are limited to the integration test harness, its Hatch
  command, the Windows workflow, and test documentation.

### Was this change documented?

The modified integration-test functions include updated docstrings, and
`test/AGENTS.md` documents the in-process execution and hang diagnostics. No
README, schema, or customer-facing documentation changes are required.

### Is this a breaking change?

No. This change is limited to integration test behavior and does not modify any
public contract or customer-facing functionality.

----

*By submitting this pull request, I confirm that you can use, modify, copy, and redistribute this contribution, under the terms of your choice.*
