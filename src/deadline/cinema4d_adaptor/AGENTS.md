# AGENTS.md — cinema4d_adaptor

Worker-side component that runs Cinema 4D renders on Deadline Cloud. Exposed as the `cinema4d-openjd` CLI.

## Two-Part Architecture

### Cinema4DAdaptor (`Cinema4DAdaptor/`)

The adaptor server — a command-line app that manages the Cinema 4D process lifecycle on workers. Built on the [OpenJD Adaptor Runtime](https://github.com/OpenJobDescription/openjd-adaptor-runtime-for-python).

**Key files:**
- `adaptor.py` — Main adaptor class, lifecycle management (`on_start`, `on_run`, `on_end`)
- `schemas/init_data.schema.json` — Schema for initialization data (once per job)
- `schemas/run_data.schema.json` — Schema for per-task data (per frame/take)

**Responsibilities:**
- Start/stop Cinema 4D process with Cinema4DClient
- Send initialization actions (scene file, renderer settings)
- Send per-task actions (frame number, output path, take)
- Parse stdout/stderr for progress reporting via regex handlers
- Handle errors and logging

### Cinema4DClient (`Cinema4DClient/`)

Runs inside the Cinema 4D process. Acts as a secure web server over named pipes, receiving commands from the adaptor to control Cinema 4D.

**Key files:**
- `cinema4d_client.py` — Main client class, action routing, named pipe server
- `cinema4d_handler.py` — Action handlers for scene loading, rendering, etc.
- `tile_rendering.py` — Tile rendering support
- `plugin/` — Cinema 4D plugin files for client integration

**Responsibilities:**
- Receive actions from adaptor via named pipes
- Route actions to appropriate handler methods in `cinema4d_handler.py`
- Execute `c4d` module commands to control Cinema 4D
- Report progress and errors back to adaptor

## Action-Based Communication Model

```
Adaptor (cinema4d-openjd)
    → enqueue_action(action_name, data)
    → Cinema4DClient receives action via named pipe
    → Cinema4DClient routes to handler method in cinema4d_handler.py
    → Handler executes c4d API calls
    → Result sent back to adaptor
```

### Registering a new action

In `Cinema4DClient/cinema4d_handler.py`:

```python
class Cinema4DHandler:
    def __init__(self):
        self.action_dict = {
            "scene_file": self.set_scene_file,
            "render": self.start_render,
            # NEW: Add your action here
            "my_action": self.handle_my_action,
        }

    def handle_my_action(self, data: dict) -> None:
        """Handle my custom action."""
        # Implementation using c4d module
        pass
```

### Progress reporting

The adaptor parses Cinema 4D stdout/stderr via regex handlers registered in `adaptor.py`:

```python
self._stdout_handlers = [
    RegexHandler(
        regex=r"Rendering frame (\d+)/(\d+)",
        callback=self._handle_progress,
    ),
]
```

## Schema Versioning — IMPORTANT

When modifying `Cinema4DAdaptor/schemas/init_data.schema.json` or `run_data.schema.json`, you **must** also update `integration_data_interface_version` in `adaptor.py` following semantic versioning. The submitter checks this version to ensure compatibility.

## Path Mapping

Assets may be at different paths on worker vs. artist workstation. The OpenJD adaptor runtime provides path mapping support that translates paths between platforms. Use the runtime's path mapping utilities rather than hardcoding paths.

## Adaptor Modes

Two modes of operation:

**Direct run** — simpler, for rapid iteration:
```bash
cinema4d-openjd run --init-data file://<init.yaml> --run-data file://<run.yaml>
```

**Daemon mode** — for testing sticky rendering across multiple runs:
```bash
cinema4d-openjd daemon start --init-data file://<init.yaml> --connection-file file://connection-info.json
cinema4d-openjd daemon run --run-data file://<run.yaml> --connection-file file://connection-info.json
cinema4d-openjd daemon stop --connection-file file://connection-info.json
```

When testing daemon mode, run multiple `daemon run` commands with different inputs before `daemon stop` to catch data carryover issues.

## Testing the Adaptor

For testing adaptor changes on a live Deadline Cloud farm, build a patched conda package from the public [cinema4d-openjd conda recipe](https://github.com/aws-deadline/deadline-cloud-samples/tree/mainline/conda_recipes/cinema4d-openjd).
