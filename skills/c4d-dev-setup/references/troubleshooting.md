# Troubleshooting Guide

Common issues and solutions for Cinema 4D dev setup.

## Cinema 4D Not Found

**Problem:** Setup aborts with "Cinema 4D {VERSION} is not installed"

**Solutions:**
1. Verify Cinema 4D is installed at the standard location:
   - Windows: `C:\Program Files\Maxon Cinema 4D {VERSION}`
   - macOS: `/Applications/Maxon Cinema 4D {VERSION}`
2. Install Cinema 4D from the [Maxon website](https://www.maxon.net/en/cinema-4d)
3. Check if you have the correct version installed (2024, 2025, or 2026)

## Hatch Installation Issues

**Problem:** `hatch: command not found`

**Solutions:**
1. Verify hatch is installed:
   ```bash
   pip list | grep hatch
   ```
2. Restart terminal after installation
3. Install explicitly:
   ```bash
   pip install hatch
   ```

## Build Failures

**Problem:** `hatch build` fails

**Solutions:**
1. Ensure you're in the repository root directory
2. Check if git is initialized (hatch-vcs requires git):
   ```bash
   git status
   ```
3. Verify Python version:
   ```bash
   python3 --version  # Should be 3.10+
   ```
4. Clean build artifacts and retry:
   ```bash
   rm -rf dist build *.egg-info
   hatch build
   ```
5. Prune hatch environments:
   ```bash
   hatch env prune
   ```

## Submitter Installation Issues

**Problem:** Submitter not visible in Cinema 4D

**Solutions:**
1. Verify environment variables are set:
   - `C4DPYTHONPATH311` → Points to submitter installation
   - `g_additionalModulePath` → Points to cinema_4d_plugins directory
2. Restart Cinema 4D completely after setting env vars
3. On macOS, launch Cinema 4D via the generated `Cinema4D.command` script
4. Check Cinema 4D console (`Extensions > Console`) for import errors

## PySide6 Import Errors

**Problem:** `PySide6/__init__.py: Unable to import Shiboken from ...`

**Solutions:**
1. Update to Cinema 4D 2024.4.0+ (resolves missing libraries)
2. Manually install missing module:
   ```
   # Windows
   "C:\Program Files\Maxon Cinema 4D {VERSION}\resource\modules\python\libs\win64\python.exe" -m pip install MISSING_MODULE
   ```

## Licensing Issues

### Cinema 4D License Not Found

**Problem:** Cinema 4D shows license error on startup

**Solutions:**
1. Verify your license server is accessible
2. Configure Cinema 4D license settings appropriately for your environment
3. Check that the license server environment variable is set:
   ```powershell
   $env:g_licenseServerURL = "<your-license-server>:<port>"
   ```

### Redshift License Not Found

**Problem:** Redshift renders fail with license error

**Solutions:**
1. Set the Redshift license environment variable:
   ```bash
   # Windows PowerShell
   $env:redshift_LICENSE = "<port>@<your-license-server>"

   # macOS/Linux
   export redshift_LICENSE="<port>@<your-license-server>"
   ```
2. Verify your license server is accessible

## Integration Test Issues

### pywin32 Errors (Windows)

**Problem:** Integration tests fail with pywin32 DLL errors

**Solutions:**
1. Install pywin32 version 308:
   ```powershell
   pip install pywin32==308 -t "C:\Program Files\Maxon Cinema 4D {VERSION}\resource\modules\python\libs\win64\lib\site-packages"
   ```
2. Copy DLLs manually:
   - Copy `pythoncom311.dll` and `pywintypes311.dll`
   - From: `...\pywin32_system32\`
   - To: `...\dlls\`

### Tests Hang

**Problem:** Integration tests hang indefinitely

**Solutions:**
1. Cinema 4D may be waiting for license input. Kill stuck processes:
   ```powershell
   Get-Process *Cinema* | Stop-Process -Force
   Get-Process *Commandline* | Stop-Process -Force
   ```
2. Verify licensing is configured correctly

### Non-ASCII Path Errors

**Problem:** Tests with non-ASCII characters fail

**Solutions:**
1. Set encoding:
   ```powershell
   $env:PYTHONIOENCODING = "utf-8"
   ```

## Python Version Mismatch

**Problem:** Wrong Python version being used

**Solutions:**
1. Cinema 4D 2026 uses Python 3.11, Cinema 4D 2024-2025 uses Python 3.10
2. For unit tests, your system Python 3.10+ is fine
3. For integration tests, Cinema 4D's bundled Python is used automatically

## Getting Help

If issues persist:
1. Check project documentation: `README.md`, `DEVELOPMENT.md`, `docs/software_arch.md`
2. Check Cinema 4D console: `Extensions > Console`
3. Review Cinema 4D logs for detailed error messages
4. Try a clean setup: `hatch env prune`, rebuild, reinstall
