# This file is used only for integration tests.
from .cinema4d_render_submitter import (
    show_submitter
)

from qtpy import QtWidgets

def find_button_by_text(dialog, text):
    for button in dialog.findChildren(QtWidgets.QPushButton):
        if button.text() == text:
            return button
    return None

def close_all_dialogs():
    print("In close all dialogs")
    for widget in QtWidgets.QApplication.topLevelWidgets():
        print(f"Im in this widget: {widget}")
        widget.close()

def submitter_dialog_test(job_bundle_override_dir: str):

    try:
        dialog = show_submitter(test=True, job_bundle_override_dir=job_bundle_override_dir)
        print(f"Dialog: {dialog}")

        button = find_button_by_text(dialog=dialog, text="Export bundle")
        print(f"Button {button}")

        button.click()
        print("Clicked button")

        # close_all_dialogs()
    except Exception as e:
        print(f"Submitter dialog test failed: {e}")
        import traceback

        traceback.print_exc()
