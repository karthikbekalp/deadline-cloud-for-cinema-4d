# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Dialog configurator for the `cube` test case.

`test_cinema4d.py` loads the top-level ``configure(dialog)`` function below and
runs it against the submitter dialog after it loads and before Export bundle is
pressed. It exercises a spread of Shared and Job-specific settings via the
``submitter_ui`` page-object.

Every change here is **render-neutral** -- it alters job metadata, logging, and
the output *directory name*, but not the rendered pixels -- so the expected
renders are unchanged. The changes do alter the exported bundle, so
``expected/job_bundle/`` reflects the post-configure state (re-capture it if you
change anything here; see test/AGENTS.md).
"""

from test.integ_xa11y import submitter_ui as ui


def configure(dialog):
    # --- Shared job settings ---
    ui.set_job_name(dialog, "cube_configured")
    ui.set_priority(dialog, 75)  # default 50
    ui.set_max_failed_tasks(dialog, 10)  # default 20
    ui.set_max_retries(dialog, 3)  # default 5

    # --- Job-specific settings ---
    ui.set_detailed_logging(dialog, True)
    # Override the output path, renaming the leaf dir renders -> render. Pixels
    # are identical; only the OutputPath in the bundle changes. The test derives
    # the render-compare dir from OutputPath, so it follows this automatically.
    ui.override_output_path(dialog, lambda p: p.replace("renders", "render"))
    # Bump the first Task Run timeout spinner (the Timeouts group's 1st field) to
    # exercise that group. Units are the spinner's own (days for this field).
    ui.set_timeout(dialog, nth=1, value=5)
