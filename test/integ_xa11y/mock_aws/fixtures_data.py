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

The Conda queue-environment template below is retained for reference only -- it
is not served while the queue-environment list is empty.
"""

from __future__ import annotations

# --- Sanitized identifiers (fake, but well-formed) -------------------------

FAKE_ACCOUNT_ID = "123456789012"
FARM_ID = "farm-0000000000000000000000000000000a"
QUEUE_ID = "queue-0000000000000000000000000000000b"
CONDA_QUEUE_ENV_ID = "queueenv-0000000000000000000000000000000c"

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

# The Conda queue-environment template, verbatim from the live farm. This drives
# the CondaPackages / CondaChannels parameters that appear in the exported
# bundle's parameter_values.yaml, so it must stay byte-faithful.
CONDA_QUEUE_ENV_TEMPLATE = """\
specificationVersion: "environment-2023-09"
parameterDefinitions:
 - name: CondaPackages
   type: STRING
   description: >
    This is a space-separated list of Conda package match specifications to
    install for the job. E.g. "blender=3.6" for a job that renders frames in
    Blender 3.6.

    See
    https://docs.conda.io/projects/conda/en/latest/user-guide/concepts/pkg-specs.html#package-match-specifications
   default: ""
   userInterface:
    control: LINE_EDIT
    label: Conda Packages
 - name: CondaChannels
   type: STRING
   description: >
    This is a space-separated list of Conda channels from which to install
    packages. Deadline Cloud SMF packages are installed from the
    "deadline-cloud" channel that is configured by Deadline Cloud.

    Add "conda-forge" to get packages from the https://conda-forge.org/
    community, and "defaults" to get packages from Anaconda Inc (make sure your
    usage complies with https://www.anaconda.com/terms-of-use).
   default: "deadline-cloud"
   userInterface:
    control: LINE_EDIT
    label: Conda Channels
environment:
 name: Conda
 script:
  actions:
   onEnter:
    command: "conda-queue-env-enter"
    args:
     [
      "{{Session.WorkingDirectory}}/.env",
      "--packages",
      "{{Param.CondaPackages}}",
      "--channels",
      "{{Param.CondaChannels}}"
     ]
   onExit:
    command: "conda-queue-env-exit"
"""

# Summary entry returned by ListQueueEnvironments (id + name + priority only;
# the full template comes from GetQueueEnvironment).
CONDA_QUEUE_ENV_SUMMARY: dict = {
    "queueEnvironmentId": CONDA_QUEUE_ENV_ID,
    "name": "Conda",
    "priority": 10,
}

# Full GetQueueEnvironment response for the Conda env.
GET_CONDA_QUEUE_ENV_RESPONSE: dict = {
    "queueEnvironmentId": CONDA_QUEUE_ENV_ID,
    "name": "Conda",
    "priority": 10,
    "templateType": "YAML",
    "template": CONDA_QUEUE_ENV_TEMPLATE,
    "createdAt": "2025-03-16T06:24:04+00:00",
    "createdBy": _FAKE_PRINCIPAL,
    "updatedAt": "2025-03-16T06:27:18+00:00",
    "updatedBy": _FAKE_PRINCIPAL,
}
