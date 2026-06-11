# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Page-object helpers for driving the Deadline Cloud submitter dialog via xa11y.

A test case drives the dialog through a ``configure(dialog)`` function (see
``input/configure.py`` in a test case, and ``DialogConfigurator`` in
``test_cinema4d.py``). That function runs after the dialog has loaded and before
Export bundle is pressed, so it can switch tabs, set parameters, and toggle
options instead of exporting the dialog's defaults.

This module is the toolkit those configurators build on. It has two layers:

* **Primitives** (``switch_to_tab``, ``set_text_field``, ``set_spin_button``,
  ``toggle_checkbox``, ``select_combo``) -- one robust pattern per widget type.
* **Semantic helpers** (``set_priority``, ``set_max_failed_tasks``,
  ``set_job_name``, ``set_detailed_logging``, ``override_output_path``,
  ``set_timeout``) -- named for what they change, hiding the selector trivia
  (which tab, which ``.nth()`` index) so a ``configure.py`` reads as intent.

Prefer the semantic helpers in configurators; reach for primitives for one-offs.


Finding selectors
------------------
You cannot guess accessible names -- harvest them with the ``DIALOG_DUMP=1`` dump
mode (see "Finding selectors" in test/AGENTS.md). Each dumped line is
``<role> "<name>" value="<value>"``; match on role + name with
``dialog.descendant("<role>[name='<name>']")``.


Cross-platform contract
-----------------------
The helpers below are verified on **both** macOS (AX) and Windows (UIA).
Accessible roles and names can differ between the two backends, so the selectors
here are written to match either (and were harvested from the live tree on each
platform -- see "Finding selectors" in test/AGENTS.md). If you add a selector,
verify it on both; when one misses, the failure dumps that platform's tree.


Gotchas the live tree reveals (and source code hides)
-----------------------------------------------------
* **The tab control's role differs by backend** -- Windows UIA exposes each tab
  as ``tab`` (inside a ``tab_group``), macOS AX as ``radio_button``.
  ``switch_to_tab`` matches either.
* **Many fields share an accessible name.** Qt's ``QFormLayout`` does not give a
  field its label as its accessible name: on the Shared tab the Priority,
  Maximum-failed-tasks, and Maximum-retries spin boxes all surface as
  ``spin_button "Job Properties"`` (only the Name field is uniquely named). The
  Job-specific tab's text fields have no usable name (empty on macOS, none on
  Windows). Disambiguate by role + ``.nth(n)`` (1-based, tree order) or by
  scoping to a parent ``group`` first.
* **Spin boxes step, they don't set.** ``set_value`` / ``set_numeric_value`` do
  not work on these Qt spin boxes (one raises, the other silently no-ops).
  ``set_spin_button`` drives them with ``increment()`` / ``decrement()`` and
  reads the value back. Text fields and checkboxes behave normally
  (``set_value`` / ``toggle``).
* **Always wait before acting.** Widgets settle asynchronously; the primitives
  ``wait_visible`` first.


Watching it run
---------------
Interactions fly by too fast to see. Set ``DIALOG_CONFIG_OBSERVE_DELAY_S`` to
pause after each change so you can watch the dialog update::

    DIALOG_CONFIG_OBSERVE_DELAY_S=1.5 hatch -e integ-xa11y run pytest --no-cov \
        test/integ_xa11y/test_cinema4d.py --numprocesses=0 -s -k <case>

Defaults to 0 (no slowdown) for CI and normal runs.
"""

from __future__ import annotations

import os
import time

import xa11y

# Generous timeout for dialog widgets (matches the test's other waits).
_WIDGET_TIMEOUT_S = 60.0

# Pause after each interaction so a human watching the run can see each change
# land. Default 0 (no slowdown); set DIALOG_CONFIG_OBSERVE_DELAY_S=1.5 to eyeball.
_OBSERVE_DELAY_S = float(os.environ.get("DIALOG_CONFIG_OBSERVE_DELAY_S", "0"))

# Tab names (radio_button accessible names).
TAB_SHARED = "Shared job settings"
TAB_JOB_SPECIFIC = "Job-specific settings"


def _observe_pause() -> None:
    """Pause briefly so a human can watch the last change. No-op unless
    DIALOG_CONFIG_OBSERVE_DELAY_S is set."""
    if _OBSERVE_DELAY_S > 0:
        time.sleep(_OBSERVE_DELAY_S)


# ==========================================================================
# Layer 1 -- per-widget-type primitives.
# ==========================================================================


def switch_to_tab(dialog: xa11y.Locator, tab_name: str) -> None:
    """Switch tabs, then give the new tab a moment to populate before touching
    its widgets.

    The tab control's role differs by accessibility backend: Windows UIA exposes
    each tab as ``tab`` (inside a ``tab_group``), while macOS AX exposes them as
    ``radio_button``. Match either."""
    tab = dialog.descendant(f"tab[name='{tab_name}'], radio_button[name='{tab_name}']")
    tab.wait_visible(timeout=_WIDGET_TIMEOUT_S)
    tab.press()
    time.sleep(0.5)  # let the tab's widgets attach
    _observe_pause()


def set_text_field(dialog: xa11y.Locator, name: str, value: str, nth: int | None = None) -> str:
    """Set a text field's value and return its prior value.

    Match by accessible `name`; when several share a name (or are empty-named),
    pass `nth` (1-based, tree order) to pick one. Text fields accept ``set_value``
    (unlike spin boxes)."""
    field = dialog.descendant(f"text_field[name='{name}']")
    if nth is not None:
        field = field.nth(nth)
    field.wait_visible(timeout=_WIDGET_TIMEOUT_S)
    previous = field.element().value or ""
    field.set_value(value)
    _observe_pause()
    return previous


def set_spin_button(dialog: xa11y.Locator, name: str, nth: int, target: int) -> None:
    """Drive the nth (1-based, tree order) spin button matching `name` to
    `target` by stepping toward it, reading the value back each step.

    Spin boxes must be stepped, not set: ``set_value`` / ``set_numeric_value`` do
    not work on them (one raises, the other silently no-ops). A single
    ``increment()`` can occasionally advance more than one, so
    we don't trust a fixed step count -- we read ``.value`` each time and stop on
    the target. The bounded loop just prevents spinning forever on an
    unreachable target (e.g. outside the box's range)."""
    spin = dialog.descendant(f"spin_button[name='{name}']").nth(nth)
    spin.wait_visible(timeout=_WIDGET_TIMEOUT_S)
    current = int(spin.element().value or "0")
    for _ in range(10_000):
        if current == target:
            return
        if current < target:
            spin.increment()
        else:
            spin.decrement()
        _observe_pause()
        current = int(spin.element().value or "0")
    raise AssertionError(f"spin button {name!r} nth({nth}) did not reach {target} (at {current})")


def set_spin_button_in_group(dialog: xa11y.Locator, group: str, nth: int, target: int) -> None:
    """Like ``set_spin_button`` but scopes to a parent ``group`` first, for spin
    boxes that have no accessible name of their own (e.g. the Timeouts group's
    fields surface as ``spin_button ""``)."""
    spin = dialog.descendant(f"group[name='{group}']").descendant("spin_button").nth(nth)
    spin.wait_visible(timeout=_WIDGET_TIMEOUT_S)
    current = int(spin.element().value or "0")
    for _ in range(10_000):
        if current == target:
            return
        if current < target:
            spin.increment()
        else:
            spin.decrement()
        _observe_pause()
        current = int(spin.element().value or "0")
    raise AssertionError(f"spin button in group {group!r} nth({nth}) did not reach {target}")


def _is_checked(box) -> bool:
    """True if a checkbox element is checked. xa11y's `checked` is a string
    ('on'/'off' on macOS AX), so compare explicitly -- bool() on the raw string
    is always True (even for 'off')."""
    return (box.element().checked or "").lower() in ("on", "true", "1", "checked")


def toggle_checkbox(dialog: xa11y.Locator, name: str) -> None:
    """Toggle a checkbox by its (usually unique) name."""
    box = dialog.descendant(f"check_box[name='{name}']")
    box.wait_visible(timeout=_WIDGET_TIMEOUT_S)
    box.toggle()
    _observe_pause()


def set_checkbox(dialog: xa11y.Locator, name: str, checked: bool) -> None:
    """Set a checkbox to a desired state, toggling only if it isn't already
    there (reads the 'on'/'off' state via _is_checked)."""
    box = dialog.descendant(f"check_box[name='{name}']")
    box.wait_visible(timeout=_WIDGET_TIMEOUT_S)
    if _is_checked(box) != checked:
        box.toggle()
        _observe_pause()


def select_combo(dialog: xa11y.Locator, current_name: str) -> None:
    """Open a combo box (matched by its currently-shown value). ``.select()``
    activates it; how you then pick an item depends on whether the popup list
    surfaces as its own elements -- dump the tree after ``.select()`` to see."""
    combo = dialog.descendant(f"combo_box[name='{current_name}']")
    combo.wait_visible(timeout=_WIDGET_TIMEOUT_S)
    combo.select()
    _observe_pause()


# ==========================================================================
# Layer 2 -- semantic helpers (named for the setting they change).
# The .nth() indices below are pinned from the live dialog tree (verified on
# macOS and Windows); re-dump and re-check them if the submitter's layout changes.
# ==========================================================================


def set_job_name(dialog: xa11y.Locator, name: str) -> None:
    """Shared tab: the job Name (the only uniquely-named text field there)."""
    switch_to_tab(dialog, TAB_SHARED)
    set_text_field(dialog, "Name", name)


def set_priority(dialog: xa11y.Locator, value: int) -> None:
    """Shared tab: Priority -- the 1st "Job Properties" spin button."""
    switch_to_tab(dialog, TAB_SHARED)
    set_spin_button(dialog, "Job Properties", 1, value)


def set_max_failed_tasks(dialog: xa11y.Locator, value: int) -> None:
    """Shared tab: Maximum failed tasks count -- the 2nd "Job Properties" spin."""
    switch_to_tab(dialog, TAB_SHARED)
    set_spin_button(dialog, "Job Properties", 2, value)


def set_max_retries(dialog: xa11y.Locator, value: int) -> None:
    """Shared tab: Maximum retries per task -- the 3rd "Job Properties" spin."""
    switch_to_tab(dialog, TAB_SHARED)
    set_spin_button(dialog, "Job Properties", 3, value)


def set_detailed_logging(dialog: xa11y.Locator, enabled: bool) -> None:
    """Job-specific tab: the "Activate detailed logging" checkbox."""
    switch_to_tab(dialog, TAB_JOB_SPECIFIC)
    set_checkbox(dialog, "Activate detailed logging", enabled)


def override_output_path(dialog: xa11y.Locator, transform) -> str:
    """Job-specific tab: enable "Override Output Path" and rewrite the path.

    `transform` takes the field's current path string and returns the new one
    (so a configurator stays path-agnostic -- it never hard-codes the test's
    absolute paths). Returns the new path.

    The override field is the 1st text field on this tab (immediately after the
    "Override Output Path" checkbox). It is matched by role alone -- the field
    carries no accessible name on either backend (macOS exposes an empty name,
    Windows exposes none), and in preorder the tab's unnamed text fields are
    output-path (1st), multi-pass (2nd), frame-range (3rd)."""
    switch_to_tab(dialog, TAB_JOB_SPECIFIC)
    toggle_checkbox(dialog, "Override Output Path")
    field = dialog.descendant("text_field").nth(1)
    field.wait_visible(timeout=_WIDGET_TIMEOUT_S)
    current = field.element().value or ""
    new_value = transform(current)
    field.set_value(new_value)
    _observe_pause()
    return new_value


def set_timeout(dialog: xa11y.Locator, nth: int, value: int) -> None:
    """Job-specific tab: a Timeouts-group spin button (empty-named, so scoped to
    the "Timeouts" group). `nth` is 1-based within that group; `value` is in the
    spinner's own units (the group mixes day/hour/minute fields)."""
    switch_to_tab(dialog, TAB_JOB_SPECIFIC)
    set_spin_button_in_group(dialog, "Timeouts", nth, value)
