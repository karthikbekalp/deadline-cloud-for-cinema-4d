# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Ground-truth response data for the mock Deadline backend.

These values were originally captured from a live Deadline Cloud farm, then
**sanitized**: real account ids, role ARNs, S3 bucket name, and operator
principal were replaced with obviously-fake placeholders. Only the response
*shapes* need to be faithful.

Call set for the Export-bundle flow (telemetry opted out, so no STS):
``ListFarms``, ``GetFarm``, ``GetQueue``, ``ListQueueEnvironments``. The mock
returns an empty queue-environment list (see ``deadline.py``), so the submitter
never calls ``GetQueueEnvironment`` and the exported bundle carries no
``CondaPackages`` / ``CondaChannels``.
"""

from __future__ import annotations

# --- Sanitized identifiers (fake, but well-formed) -------------------------

FAKE_ACCOUNT_ID = "123456789012"
FARM_ID = "farm-0000000000000000000000000000000a"
QUEUE_ID = "queue-0000000000000000000000000000000b"

FARM_DISPLAY_NAME = "TestFarm"
QUEUE_DISPLAY_NAME = "TestQueue"

_FAKE_PRINCIPAL = f"arn:aws:sts::{FAKE_ACCOUNT_ID}:assumed-role/Admin/mock-tester"
_FAKE_QUEUE_ROLE = f"arn:aws:iam::{FAKE_ACCOUNT_ID}:role/service-role/MockDeadlineCloudQueueRole"

# --- Captured (sanitized) response bodies ----------------------------------
# Timestamps are fixed ISO-8601 strings; the real client only displays them.

GET_FARM_RESPONSE: dict = {
    "farmId": FARM_ID,
    "displayName": FARM_DISPLAY_NAME,
    "description": "",
    "createdAt": "2024-09-02T14:40:19+00:00",
    "createdBy": _FAKE_PRINCIPAL,
    "updatedAt": "2025-02-24T13:37:42+00:00",
    "updatedBy": _FAKE_PRINCIPAL,
    "costScaleFactor": 1.0,
}

GET_QUEUE_RESPONSE: dict = {
    "farmId": FARM_ID,
    "queueId": QUEUE_ID,
    "displayName": QUEUE_DISPLAY_NAME,
    "status": "SCHEDULING",
    "defaultBudgetAction": "NONE",
    "description": "",
    "createdAt": "2025-02-24T19:30:23+00:00",
    "createdBy": _FAKE_PRINCIPAL,
    "updatedAt": "2026-03-23T19:04:56+00:00",
    "updatedBy": _FAKE_PRINCIPAL,
    "jobAttachmentSettings": {
        "s3BucketName": "mock-deadline-cloud-bucket",
        "rootPrefix": "DeadlineCloud",
    },
    "roleArn": _FAKE_QUEUE_ROLE,
    "schedulingConfiguration": {"priorityFifo": {}},
}
