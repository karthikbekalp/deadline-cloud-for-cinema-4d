# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Cinema 4D-specific controls for the Deadline submitter dialog.

Cross-platform Qt widget primitives and shared job settings live in
``deadline_test_fixtures.xa11y.controls``. This module re-exports them so case
configurators keep a single import, and defines only controls owned by the
Cinema 4D submitter.
"""

from __future__ import annotations

from typing import Callable

import xa11y
from deadline_test_fixtures.xa11y.controls import (
    TAB_JOB_SPECIFIC,
    TAB_SHARED,
    set_checkbox,
    set_job_name,
    set_max_failed_tasks,
    set_max_retries,
    set_priority,
    set_spin_button_in_group,
    switch_to_tab,
    toggle_checkbox,
    transform_text_field,
)

__all__ = [
    "TAB_JOB_SPECIFIC",
    "TAB_SHARED",
    "override_output_path",
    "set_detailed_logging",
    "set_job_name",
    "set_max_failed_tasks",
    "set_max_retries",
    "set_priority",
    "set_timeout",
    "switch_to_tab",
]


def set_detailed_logging(dialog: xa11y.Locator, enabled: bool) -> None:
    """Enable or disable Cinema 4D's detailed logging scripts."""
    switch_to_tab(dialog, TAB_JOB_SPECIFIC)
    set_checkbox(dialog, "Activate detailed logging", enabled)


def override_output_path(
    dialog: xa11y.Locator,
    transform: Callable[[str], str],
) -> str:
    """Enable the C4D output override and transform its current path."""
    switch_to_tab(dialog, TAB_JOB_SPECIFIC)
    toggle_checkbox(dialog, "Override Output Path")
    field = dialog.descendant("text_field").nth(1)
    field.wait_visible(timeout=60.0)
    return transform_text_field(field, transform)


def set_timeout(dialog: xa11y.Locator, nth: int, value: int) -> None:
    """Set a Cinema 4D Timeouts-group spinner by one-based tree position."""
    switch_to_tab(dialog, TAB_JOB_SPECIFIC)
    set_spin_button_in_group(dialog, "Timeouts", nth, value)
