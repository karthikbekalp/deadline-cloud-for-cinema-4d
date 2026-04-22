# Troubleshooting Guide

Common issues and solutions when developing deadline-cloud-for-cinema-4d.

## Build Issues

### "No wheel files found in dist directory"
```bash
hatch build
```

### Hatch not found
```bash
pip install hatch
```

### Build fails with version error
Hatch-vcs requires a git repository. Ensure you cloned the repo (not downloaded a zip):
```bash
git status
```

If the `.git` folder is missing, re-clone:
```bash
git clone https://github.com/aws-deadline/deadline-cloud-for-cinema-4d.git
```

### Hatch environment issues
If builds or tests behave unexpectedly, prune all environments:
```bash
hatch env prune
```

## Test Issues

### Unit tests fail with import errors
```bash
pip install -r requirements-testing.txt
# Or use hatch environment (handles deps automatically)
hatch run test
```

### Coverage below threshold
The project requires minimum 23% coverage. If adding new code without tests, the coverage check may fail. Add unit tests or adjust the threshold in `pyproject.toml` under `[tool.coverage.report]`.

### Integration tests hang
Cinema 4D may be waiting for license input or a dialog. Kill stuck processes:

```powershell
Get-Process *Cinema* | Stop-Process -Force
Get-Process *Commandline* | Stop-Process -Force
```

### Integration tests fail with license errors
Verify licensing environment variables are set:
```powershell
# Cinema 4D
$env:g_licenseServerURL = "<your-license-server>:<port>"

# Redshift
$env:redshift_LICENSE = "<port>@<your-license-server>"
```

## Submitter Issues

### Submitter not visible in Cinema 4D
Check that environment variables are set:
- `C4DPYTHONPATH311` — Points to the submitter installation location
- `g_additionalModulePath` — Points to the cinema_4d_plugins directory containing `DeadlineCloud.pyp`

Restart Cinema 4D after setting environment variables.

### PySide6 import errors
Some Cinema 4D versions (e.g., 2024.1.0) are missing libraries. Errors look like:
```
PySide6/__init__.py: Unable to import Shiboken from ...
```

**Solutions:**
1. Update to a later Cinema 4D version (e.g., 2024.4.0+)
2. Manually install the missing module:
   ```
   "C:\Program Files\Maxon Cinema 4D 2024\resource\modules\python\libs\win64\python.exe" -m ensurepip
   "C:\Program Files\Maxon Cinema 4D 2024\resource\modules\python\libs\win64\python.exe" -m pip install MISSING_MODULE
   ```

### Submitter changes not taking effect
After modifying submitter code:
1. Copy the updated source over the installed submitter (quick iteration)
2. Or reinstall the package (rebuild wheel and reinstall)
3. Restart Cinema 4D completely

## Adaptor Issues

### cinema4d-openjd command not found
Ensure the adaptor is installed and on PATH:
```bash
pip install deadline-cloud-for-cinema-4d
cinema4d-openjd --help
```

### Cinema 4D executable not found
Set the `C4D_COMMANDLINE_EXECUTABLE` environment variable:
```powershell
$env:C4D_COMMANDLINE_EXECUTABLE = "C:\Program Files\Maxon Cinema 4D 2026\Commandline.exe"
```

Or add Cinema 4D to PATH.

### Adaptor schema changes
When modifying `init_data.schema.json` or `run_data.schema.json`, you **must** also update the `integration_data_interface_version` in `adaptor.py` following semantic versioning.

## Renderer Issues

### Redshift render produces black image
- Verify Redshift licensing is active
- Check GPU drivers: NVIDIA GRID driver 551.78+ required
- Ensure sufficient RAM (at least 2x VRAM)

### Redshift freezing on Linux
Known sporadic issue. Workaround: set timeouts via the submitter's job-specific settings.

### Arnold (C4DtoA) crashes on Linux 2026
Known issue. Requires c4dtoa 4.8.6.2+ with GPU driver 580.127+. See [GitHub issue #386](https://github.com/aws-deadline/deadline-cloud-for-cinema-4d/issues/386).

### Adobe Substance Materials crash on Linux
Known issue on Amazon Linux 2023. Scenes crash at "Baking Substance Materials" step. Works on RHEL 9/10. See [GitHub issue #297](https://github.com/aws-deadline/deadline-cloud-for-cinema-4d/issues/297).

### V-Ray render issues
- V-Ray is supported on Windows and macOS only
- Ensure V-Ray is installed and licensed

## Path and Encoding Issues

### Non-ASCII characters in paths
Set the encoding environment variable:
```powershell
$env:PYTHONIOENCODING = "utf-8"
```

### Scene file not found
- Verify the file exists at the specified path
- Use forward slashes in YAML/JSON configuration
- Check `parameter_values.yaml` paths match actual file locations

## pywin32 Issues (Windows)

### pywin32 DLL errors during integration tests
Install pywin32 version 308 to Cinema 4D's Python:
```powershell
pip install pywin32==308 -t "C:\Program Files\Maxon Cinema 4D 2026\resource\modules\python\libs\win64\lib\site-packages"
```

Copy DLLs manually:
- Copy `pythoncom311.dll` and `pywintypes311.dll`
- From: `...\pywin32_system32\`
- To: `...\dlls\`

## Getting Help

If issues persist:
1. Check project documentation: `README.md`, `DEVELOPMENT.md`, `docs/software_arch.md`
2. Check Cinema 4D console: `Extensions > Console` in Cinema 4D
3. Review Cinema 4D logs for detailed error messages
4. Verify all prerequisites: Python 3.10+, Cinema 4D 2024-2026, proper licensing
5. Try a clean setup: `hatch env prune`, rebuild, reinstall
