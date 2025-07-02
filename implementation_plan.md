# Implementation Plan

## 1. Update data_classes.py

Add a new field to the `RenderSubmitterUISettings` class:

```python
export_job_bundle_to_temp: bool = field(default=True, metadata={"sticky": True})
```

## 2. Update scene_settings_tab.py

Add a new checkbox to the UI:

```python
# In _build_ui method, add after the timeout_settings_box
self.export_job_bundle_chck = QCheckBox("Export job bundle to temporary folder before submission", self)
lyt.addWidget(self.export_job_bundle_chck, 5, 0, 1, 2)

# Adjust the developer options row number
if self.developer_options:
    self.include_adaptor_wheels = QCheckBox("Developer Option: Include Adaptor Wheels", self)
    lyt.addWidget(self.include_adaptor_wheels, 6, 0)
```

Configure the checkbox with the settings:

```python
# In _configure_settings method, add:
self.export_job_bundle_chck.setChecked(settings.export_job_bundle_to_temp)
```

Update the settings when the checkbox changes:

```python
# In update_settings method, add:
settings.export_job_bundle_to_temp = self.export_job_bundle_chck.isChecked()
```

## 3. Update cinema4d_render_submitter.py

Add required imports:

```python
import tempfile
import shutil
```

Update the job bundle callback function:

```python
def on_create_job_bundle_callback(
    widget: SubmitJobToDeadlineDialog,
    job_bundle_dir: str,
    settings: RenderSubmitterUISettings,
    queue_parameters: list[dict[str, Any]],
    asset_references: AssetReferences,
    host_requirements: Optional[dict[str, Any]] = None,
    purpose: JobBundlePurpose = JobBundlePurpose.SUBMISSION,
) -> None:
    """
    Callback function for creating a job bundle when submitting the job.
    """
    # If export to temp folder is enabled, save the project to a temp directory first
    temp_dir = None
    original_cinema4d_file = None
    
    if settings.export_job_bundle_to_temp:
        doc = c4d.documents.GetActiveDocument()
        # Create a temporary directory
        temp_dir = tempfile.mkdtemp(prefix="c4d_job_bundle_")
        
        # Get the original file name and path
        original_file_name = doc.GetDocumentName()
        
        # Save the project to the temporary directory
        temp_file_path = os.path.join(temp_dir, original_file_name)
        c4d.documents.SaveProject(doc, temp_file_path, c4d.SAVEDOCUMENTFLAGS_0, c4d.FORMAT_C4DEXPORT)
        
        # Store the original Cinema4DFile value
        for param in queue_parameters:
            if param["name"] == "Cinema4DFile":
                original_cinema4d_file = param["value"]
                param["value"] = temp_file_path
                break
    
    try:
        # Continue with the existing job bundle creation
        create_job_bundle(
            settings,
            takes,
            job_bundle_dir,
            asset_references,
            queue_parameters,
            widget.job_attachments.attachments,
            host_requirements,
        )
    finally:
        # Restore the original Cinema4DFile value if we modified it
        if settings.export_job_bundle_to_temp and original_cinema4d_file is not None:
            for param in queue_parameters:
                if param["name"] == "Cinema4DFile":
                    param["value"] = original_cinema4d_file
                    break
