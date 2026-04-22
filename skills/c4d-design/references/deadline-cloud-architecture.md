# Deadline Cloud for Cinema 4D Architecture (for design work)

Quick architectural reference for design decisions. For authoritative component details, read the AGENTS.md files first — they're the source of truth:

- [`AGENTS.md`](../../../AGENTS.md) — Repo-wide architecture overview
- [`src/deadline/cinema4d_submitter/AGENTS.md`](../../../src/deadline/cinema4d_submitter/AGENTS.md) — Submitter internals
- [`src/deadline/cinema4d_adaptor/AGENTS.md`](../../../src/deadline/cinema4d_adaptor/AGENTS.md) — Adaptor and client internals
- [`test/AGENTS.md`](../../../test/AGENTS.md) — Test structure

This file covers patterns and flows that are especially relevant when designing new features.

## Data Flow: Submitter to Render

Understanding the end-to-end flow is essential for design work that spans submitter and adaptor.

### 1. Job Submission

```
User opens Extensions > AWS Deadline Cloud Submitter
    → Submitter reads scene (scene.py, takes.py, assets.py)
    → User configures settings in dialog
    → Submitter creates job bundle:
        +-- template.yaml (job definition with steps per take)
        +-- parameter_values.yaml (user settings)
        +-- asset references (scene, textures, fonts)
    → Submit to Deadline Cloud
```

### 2. Task Execution on Worker

```
Deadline Cloud assigns task to worker
    → Cinema4DAdaptor receives task
    → Adaptor starts Cinema 4D with Cinema4DClient
    → Init actions (once per job):
        +-- Load scene file
        +-- Configure renderer
        +-- Set output settings
    → Run actions (per frame/take):
        +-- Set frame number
        +-- Set take (if multi-take)
        +-- Set output path
        +-- Start render
    → Parse stdout for progress
    → Report completion to Deadline Cloud
```

### 3. Action Execution in Cinema4DClient

```
Cinema4DClient receives action via named pipe
    → Route to handler method in cinema4d_handler.py
    → Execute c4d module commands
    → Report result back to adaptor
```

## Design Considerations

### Where does your feature live?

Most features touch more than one component. Map out where each piece lives:

| Concern | Component | Files |
|---------|-----------|-------|
| User-facing UI | Submitter | `cinema4d_submitter/ui/`, `data_classes.py` |
| Scene analysis | Submitter | `scene.py`, `takes.py`, `assets.py` |
| Job template parameters | Submitter | `adaptor_cinema4d_job_template.yaml` |
| Passing data to worker | Both | `schemas/init_data.schema.json`, `schemas/run_data.schema.json` |
| Runtime logic on worker | Adaptor | `Cinema4DAdaptor/adaptor.py` |
| Cinema 4D control on worker | Client | `Cinema4DClient/cinema4d_handler.py` |

### Schema versioning

If your design changes the data contract between submitter and adaptor (either schema), you **must** bump `integration_data_interface_version` in `adaptor.py`. Consider whether the change is backwards-compatible.

### Take system interaction

Cinema 4D's take system can affect many features. Ask: should this setting be global, per-take, or both? The submitter creates separate Steps in the job template per take, and the adaptor switches takes before rendering each Step.

### Path mapping

Assets may be at different paths on worker vs. artist workstation. The OpenJD adaptor runtime provides path mapping. For any feature that references file paths, ensure they go through path mapping on the worker side.

### Renderer-specific handling

Not all renderers are available on all platforms:

| Renderer | ID | OS Support | Notes |
|----------|-----|-----------|-------|
| Physical | 1023342 | Win, Mac, Linux | Built-in |
| Standard | 0 | Win, Mac, Linux | Built-in |
| Redshift | 1036219 | Win, Linux | Bundled with C4D 2024+ |
| Arnold (C4DtoA) | varies | Win, Linux | Separate plugin |
| V-Ray | varies | Win, Mac | Separate plugin |

If your feature is renderer-specific, design how it gracefully handles unsupported renderers.

## Adding a New Feature (Design Checklist)

### Submitter side
1. Data models in `data_classes.py`
2. UI controls in `ui/` components
3. Parameters in job template YAML (`adaptor_cinema4d_job_template.yaml`)
4. Scene introspection updates if needed (`scene.py`, `takes.py`, `assets.py`)

### Data contract
5. Schema updates (`init_data.schema.json`, `run_data.schema.json`)
6. **Bump `integration_data_interface_version`** if schemas changed

### Adaptor side
7. Read parameters from job bundle in `adaptor.py`
8. Create actions to send to Cinema4DClient
9. Add stdout/stderr regex handlers if needed for progress parsing

### Client side
10. Add handler method in `cinema4d_handler.py`
11. Register action in handler's `action_dict`
12. Implement `c4d` module logic

### Testing
13. Unit tests for handler methods (mock `c4d`)
14. Unit tests for submitter logic
15. Consider adding integration test scene if rendering behavior changes
