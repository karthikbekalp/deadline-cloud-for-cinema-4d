# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Utilities for checking and displaying update notifications."""

import logging
from typing import Optional

from deadline.client.api import check_for_updates, UpdateCheckResult, UpdateCheckStatus
from deadline.client.ui.dialogs.update_available_dialog import UpdateAvailableDialog

from ._version import version_tuple as adaptor_version_tuple
from .style import C4D_STYLE

logger = logging.getLogger(__name__)


def _check_for_update() -> Optional[UpdateCheckResult]:
    """Check if a newer version of the Cinema 4D submitter is available.

    Returns:
        An UpdateCheckResult if the check succeeded, or None if it failed silently.
    """
    try:
        current_version = ".".join(str(v) for v in adaptor_version_tuple[:3])
        result = check_for_updates(
            integration_name="deadline-cloud-for-cinema-4d",
            current_version=current_version,
        )
        return result
    except Exception:
        logger.debug("Update check failed -- skipping", exc_info=True)
        return None


def check_and_show_update_dialog() -> bool:
    """Check for updates and show the update dialog if one is available.

    Returns:
        True if the user clicked Download (caller should skip opening the submitter),
        False otherwise.
    """
    update_result = _check_for_update()
    if (
        update_result
        and update_result.status == UpdateCheckStatus.SUCCESS
        and update_result.update_available
    ):
        update_dialog = UpdateAvailableDialog(
            integration_name="Cinema 4D",
            current_version=update_result.current_version or "",
            latest_version=update_result.latest_version or "",
            download_url=update_result.download_url,
            release_notes_url="https://github.com/aws-deadline/deadline-cloud-for-cinema-4d/releases",
        )
        update_dialog.setStyleSheet(C4D_STYLE)
        update_dialog.exec_()
        return update_dialog.user_downloaded
    return False
