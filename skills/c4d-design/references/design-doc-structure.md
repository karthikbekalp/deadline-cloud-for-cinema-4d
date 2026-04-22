# Design Document Structure

Every design document MUST follow this four-section structure:

## 1. Data Structures to Change or Add

Define all data model changes including:
- New dataclasses or TypedDicts
- Modifications to existing data structures (in `data_classes.py`, `enums.py`, etc.)
- Job parameter schemas
- Configuration objects
- Adaptor schema changes (`init_data.schema.json`, `run_data.schema.json`)
- Type annotations

## 2. UX Changes (Submitter Dialog)

Document all user-facing changes:
- New UI controls (dropdowns, checkboxes, text fields)
- Control placement and grouping within the submitter dialog
- Default values and validation
- Tooltips and help text
- Conditional visibility logic
- Take-specific settings

## 3. Job Template and Bundle Changes

Specify modifications to:
- `adaptor_cinema4d_job_template.yaml` structure
- `default_cinema4d_job_template.yaml` structure (if applicable)
- New parameters and their types
- Parameter dependencies and conditions
- Asset references and attachments

## 4. Adaptor and Client Changes

Detail the runtime implementation:
- Cinema4DAdaptor modifications (adaptor.py)
- Cinema4DClient changes (cinema4d_client.py, cinema4d_handler.py)
- New action handlers and commands
- Renderer-specific handling
- Path mapping considerations
- Progress reporting and logging
- stdout/stderr handler regex patterns
