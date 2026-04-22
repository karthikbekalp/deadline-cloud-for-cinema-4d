# Integration Testing Guide

How to set up and run integration tests for the Cinema 4D adaptor and submitter. **Integration tests are currently only supported on Windows.**

> For test structure, test scenes, and adding new tests, see [`test/AGENTS.md`](../../../test/AGENTS.md).

## Prerequisites

1. **Windows operating system** (integration tests are not yet supported on macOS or Linux)
2. Cinema 4D 2024, 2025, or 2026 installed
3. Redshift licensing configured (for Redshift tests)
4. Cinema 4D licensing configured
5. Python 3.10+ on system
6. Hatch installed: `pip install hatch`

## Licensing Setup

### Cinema 4D License
Set the license server environment variable:

**Windows (PowerShell):**
```powershell
$env:g_licenseServerURL = "<your-license-server-host>:<port>"
```

### Redshift License
**Windows (PowerShell):**
```powershell
$env:redshift_LICENSE = "<port>@<your-license-server-host>"
```

### Alternative: Manual License Configuration
Run `c4dpy` and `Commandline.exe` separately and set the license information through the Cinema 4D UI.

## Environment Setup

### Set Cinema 4D Location

**Windows (PowerShell):**
```powershell
$env:C4D_LOCATION = "C:\Program Files\Maxon Cinema 4D 2026\"
```

If not set, the default Windows path `C:\Program Files\Maxon Cinema 4D 2026\` is used automatically.

### Set Python Encoding
Required for non-ASCII character tests:
```powershell
$env:PYTHONIOENCODING = "utf-8"
```

### Install pywin32 (for adaptor tests)

pywin32 is required for adaptor tests on Windows:

```powershell
pip install pywin32==308 -t "C:\Program Files\Maxon Cinema 4D 2026\resource\modules\python\libs\win64\lib\site-packages"
```

Copy PyWin32 DLLs (post-install requirement):
```powershell
# Copy pythoncom311.dll and pywintypes311.dll
# From: C:\Program Files\Maxon Cinema 4D 2026\resource\modules\python\libs\win64\Lib\site-packages\pywin32_system32
# To:   C:\Program Files\Maxon Cinema 4D 2026\resource\modules\python\libs\win64\dlls
```

## Running Tests

### Run all integration tests (recommended)

```bash
hatch run integ:test
```

This uses Cinema 4D's `c4dpy` for submitter tests and `Commandline.exe` for adaptor tests.

### Run with verbose output

```bash
hatch run integ:test -vvv
```

### Run a specific test scene

```bash
hatch run integ:test -k "physical"
hatch run integ:test -k "redshift"
hatch run integ:test -k "redshift_tiles"
```

For the full list of test scenes and how to add new ones, see [`test/AGENTS.md`](../../../test/AGENTS.md).

## Common Issues

### License Not Found
Verify environment variables are set for Cinema 4D and Redshift licensing.

### pywin32 Issues
On Windows, pywin32 version 308 is required. Register DLLs if needed:
```powershell
python -m pywin32_postinstall -install
```

### Scene Generation Fails
- Verify Cinema 4D is properly installed and licensed
- Check that `c4dpy` is accessible from the Cinema 4D installation
- Ensure `PYTHONIOENCODING=utf-8` is set for non-ASCII tests

### Render Output Mismatch
- Small pixel differences may occur across GPU types
- Check that the correct renderer and version are installed
- Verify licensing is active for the renderer being tested

### Tests Hang
Cinema 4D may be waiting for license input or a dialog. Kill stuck processes:

```powershell
Get-Process *Cinema* | Stop-Process -Force
Get-Process *Commandline* | Stop-Process -Force
```
