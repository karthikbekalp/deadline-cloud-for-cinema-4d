# Research Guide for Cinema 4D Designs

This guide covers how to research and validate design decisions for Cinema 4D features.

## Cinema 4D Documentation Sources

### Official Maxon Documentation

1. **Cinema 4D Python SDK**
   - URL: https://developers.maxon.net/docs/py/2026/
   - Covers: c4d module, scene objects, materials, rendering, takes

2. **Cinema 4D C++ SDK**
   - URL: https://developers.maxon.net/docs/cpp/2026/
   - Covers: Lower-level APIs, plugin development

3. **Maxon Developer Forum**
   - URL: https://developers.maxon.net/forum/
   - Covers: Community solutions, Maxon developer responses

### Renderer Documentation

1. **Redshift for Cinema 4D**
   - URL: https://help.maxon.net/r3d/cinema/en-us/
   - Covers: Redshift render settings, AOVs, materials
   - Note: Redshift is bundled with Cinema 4D 2024+

2. **Arnold for Cinema 4D (C4DtoA)**
   - URL: https://help.autodesk.com/view/ARNOL/ENU/?guid=arnold_for_cinema_4d
   - Covers: Arnold render settings, shaders, AOVs

3. **V-Ray for Cinema 4D**
   - URL: https://docs.chaos.com/display/VC4D/
   - Covers: V-Ray render settings, materials, render elements

## Key Cinema 4D Python API Patterns

### Accessing the Active Document

```python
import c4d

doc = c4d.documents.GetActiveDocument()
```

### Accessing Render Settings

```python
# Get active render data
rd = doc.GetActiveRenderData()

# Get renderer ID
renderer_id = rd[c4d.RDATA_RENDERENGINE]

# Common renderer IDs
PHYSICAL_RENDERER = 1023342
STANDARD_RENDERER = 0
REDSHIFT_RENDERER = 1036219
```

### Accessing Takes

```python
take_data = doc.GetTakeData()
main_take = take_data.GetMainTake()
current_take = take_data.GetCurrentTake()

# Iterate takes
def iterate_takes(take):
    while take:
        print(take.GetName())
        child = take.GetDown()
        if child:
            iterate_takes(child)
        take = take.GetNext()

iterate_takes(main_take.GetDown())
```

### Scene Object Access

```python
# Get first object
obj = doc.GetFirstObject()

# Iterate all objects
def iterate_objects(obj):
    while obj:
        print(obj.GetName(), obj.GetType())
        child = obj.GetDown()
        if child:
            iterate_objects(child)
        obj = obj.GetNext()

iterate_objects(obj)

# Find object by name
obj = doc.SearchObject("ObjectName")
```

### Renderer Detection Pattern

The Cinema 4D adaptor detects renderers via the render engine ID in render settings:

```python
renderer_id = rd[c4d.RDATA_RENDERENGINE]

if renderer_id == 1036219:  # Redshift
    # Handle Redshift-specific settings
    pass
elif renderer_id == 1023342:  # Physical
    # Handle Physical renderer settings
    pass
elif renderer_id == 0:  # Standard
    # Handle Standard renderer settings
    pass
```

### Output Settings

```python
# Output path
rd[c4d.RDATA_PATH] = "/path/to/output/"

# Output format
rd[c4d.RDATA_FORMAT] = c4d.FILTER_PNG

# Frame range
rd[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(0, doc.GetFps())
rd[c4d.RDATA_FRAMETO] = c4d.BaseTime(100, doc.GetFps())

# Resolution
rd[c4d.RDATA_XRES] = 1920
rd[c4d.RDATA_YRES] = 1080
```

## Adaptor Communication Model

The Cinema 4D adaptor uses an action-based communication model:

### Action Flow
```
Adaptor (cinema4d-openjd)
    → enqueue_action(action_name, data)
    → Cinema4DClient receives action via named pipe
    → Cinema4DClient routes to handler method
    → Handler executes c4d API calls
    → Result sent back to adaptor
```

### Registering New Actions

In `cinema4d_handler.py`:
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

### Progress Reporting

The adaptor uses stdout/stderr regex handlers to parse Cinema 4D output:

```python
# In adaptor.py - regex handlers for progress reporting
self._stdout_handlers = [
    RegexHandler(
        regex=r"Rendering frame (\d+)/(\d+)",
        callback=self._handle_progress,
    ),
]
```

## Submitter Data Flow

```
Cinema 4D Scene
    → Submitter reads scene properties (scene.py, takes.py, assets.py)
    → User configures settings in dialog (ui/)
    → Settings stored in data classes (data_classes.py)
    → Job template generated (adaptor_cinema4d_job_template.yaml)
    → Job bundle created (template.yaml + parameter_values.yaml + assets)
    → Submitted to Deadline Cloud
```

## Schema Files

The adaptor uses JSON schemas to define the contract between submitter and adaptor:

- `Cinema4DAdaptor/schemas/init_data.schema.json` — Initialization data (once per job)
- `Cinema4DAdaptor/schemas/run_data.schema.json` — Per-task data (per frame/take)

**Important:** When modifying schemas, update `integration_data_interface_version` in `adaptor.py`.

## Knowledge Gap Protocol

When you encounter a knowledge gap:

1. **Document what you know**
   - What API/feature is involved?
   - What have you found so far?
   - What specific information is missing?

2. **Ask the user clearly**
   > "I need clarification on [topic]. Specifically:
   > - [Question 1]
   > - [Question 2]
   >
   > Do you have documentation or code examples for this?"

3. **Propose alternatives if possible**
   > "I'm not certain about [X], but based on [Y], I believe we could:
   > - Option A: [description]
   > - Option B: [description]
   >
   > Which approach would you prefer, or do you have more information?"

## Internet Research Guidelines

### When to Search

1. Documentation is unclear or incomplete
2. Looking for version-specific behavior (C4D 2024 vs 2025 vs 2026)
3. Finding community workarounds
4. Verifying renderer-specific API behavior

### Effective Search Queries

- `"Cinema 4D" "Python" "[topic]" site:developers.maxon.net`
- `"Redshift" "Cinema 4D" "[feature]" site:help.maxon.net`
- `"c4d" "[module]" site:stackoverflow.com`
- `"Cinema 4D" "[error message]"`
