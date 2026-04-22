# AGENTS.md — cinema4d_submitter

The Cinema 4D submitter extension. Runs inside Cinema 4D on the artist's workstation, creates job bundles, and submits them to AWS Deadline Cloud.

## Entry Point

The Cinema 4D extension is in `deadline_cloud_extension/DeadlineCloud.pyp` (repo root). It's a bare-bones plugin file that delegates all business logic to this package. The submitter is accessible in Cinema 4D via `Extensions > AWS Deadline Cloud Submitter`.

## Key Files

- `cinema4d_render_submitter.py` — Main submitter logic and entry point
- `data_classes.py` — Data models for settings and configuration
- `scene.py` — Scene introspection (renderers, output settings, cameras)
- `takes.py` — Take system handling
- `assets.py` — Asset discovery (textures, references, fonts)
- `enums.py` — Enumerations for renderers, formats, etc.
- `tile_utils.py` — Tile rendering utilities
- `font_utils.py` — Font handling and discovery
- `font_installer.py` — Font installation on workers
- `ui/` — Submitter dialog UI components (PySide6)
- `adaptor_cinema4d_job_template.yaml` — Job template used when submitting via the adaptor (default)
- `default_cinema4d_job_template.yaml` — Job template used for direct Cinema 4D command-line rendering

## Responsibilities

- Display job submission dialog
- Collect user settings (renderer, frame range, takes, output)
- Analyze scene (cameras, renderers, takes, assets)
- Create job bundle with template and assets
- Submit to Deadline Cloud

## Job Bundle

The submitter's output is a job bundle directory containing:
- `template.yaml` — Job template with parameters and steps (dynamically generated)
- `parameter_values.yaml` — User-provided parameter values
- Asset references (scene file, textures, fonts, etc.)

The template is generated dynamically from scene properties. For example, it may contain a Step for each take to render.

## Take System

Cinema 4D's take system allows multiple render configurations within a single scene. The submitter:
1. Discovers all takes in the scene (`takes.py`)
2. Allows users to select which takes to render via the UI
3. Creates separate steps in the job template for each selected take
4. The adaptor switches takes before rendering each step (see `../cinema4d_adaptor/AGENTS.md`)

## Tile Rendering

Tile rendering support for high-resolution output:
- `tile_utils.py` — Calculates tile regions on the submitter side
- `../cinema4d_adaptor/Cinema4DClient/tile_rendering.py` — Executes tile renders on workers
- Tiles are rendered as separate tasks and composited

## Adding a New Feature

When adding a new feature to the submitter:

1. Add data models to `data_classes.py`
2. Add UI controls to `ui/` components
3. Add parameters to the job template YAML (`adaptor_cinema4d_job_template.yaml`)
4. Update scene introspection if needed (`scene.py`, `takes.py`, `assets.py`)
5. Write parameter values to the bundle

If the feature requires worker-side handling, you'll also need to update the adaptor — see `../cinema4d_adaptor/AGENTS.md`. Changes to the data contract between submitter and adaptor require bumping `integration_data_interface_version`.

## Quick Iteration

For fast iteration on submitter code, copy source files directly over the installed submitter rather than rebuilding:

**Windows (PowerShell):**
```powershell
Copy-Item -Path "src\deadline\cinema4d_submitter\*" -Destination "$env:APPDATA\DeadlineCloudSubmitter\deadline\cinema4d_submitter\" -Recurse -Force
```

**macOS:**
```bash
cp -R src/deadline/cinema4d_submitter/* ~/DeadlineCloudSubmitter/deadline/cinema4d_submitter/
```

Restart Cinema 4D to pick up the changes.

## Error Handling

- Validate inputs before submission
- Collect warnings via `warning_collector.py`
- Surface issues to the user through the dialog before they submit
