# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
import os
import sys

import c4d
from deadline.cinema4d_submitter.integ_test_helpers import internal_create_job_bundle
from deadline.cinema4d_submitter.takes import TakeSelection


def main():
    doc = c4d.documents.GetActiveDocument()
    doc.Flush()
    cube = c4d.BaseObject(c4d.Ocube)
    cube[c4d.PRIM_CUBE_LEN] = c4d.Vector(200, 200, 200)
    cube.SetAbsPos(c4d.Vector(0, 170, -170))
    doc.InsertObject(cube)
    take_data = doc.GetTakeData()
    main_take = take_data.GetMainTake()

    render_settings_1 = doc.GetActiveRenderData()
    render_settings_1[c4d.RDATA_PATH] = "render's/$prj_$take"
    frame_start = c4d.BaseTime(1, doc.GetFps())
    frame_end = c4d.BaseTime(1, doc.GetFps())
    render_settings_1[c4d.RDATA_FRAMEFROM] = frame_start
    render_settings_1[c4d.RDATA_FRAMETO] = frame_end
    render_settings_1[c4d.RDATA_RENDERENGINE] = 1036219  # redshift
    render_settings_1[c4d.RDATA_FORMAT] = c4d.FILTER_JPG
    render_settings_1[c4d.RDATA_MULTIPASS_SAVEIMAGE] = False

    # Create a second render settings with a different frame range
    render_settings_2 = render_settings_1.GetClone()
    render_settings_2.InsertUnderLast(render_settings_1)
    render_settings_2.SetName("Render Settings 2")
    frame_2_start = c4d.BaseTime(2, doc.GetFps())
    frame_2_end = c4d.BaseTime(2, doc.GetFps())
    render_settings_2[c4d.RDATA_FRAMEFROM] = frame_2_start
    render_settings_2[c4d.RDATA_FRAMETO] = frame_2_end

    take_a = take_data.AddTake("", main_take, None)
    take_a.SetName("A with '")
    take_a.SetRenderData(take_data, render_settings_2)

    take_data.SetCurrentTake(main_take)

    save_dir = sys.argv[1]
    save_name = "redshift_tile_rendering.c4d"
    save_file = os.path.join(save_dir, save_name)
    doc.SetDocumentPath(save_dir)
    doc.SetDocumentName(save_name)
    c4d.documents.SaveDocument(doc, save_file, c4d.SAVEDOCUMENTFLAGS_0, c4d.FORMAT_C4DEXPORT)
    c4d.documents.InsertBaseDocument(doc)
    c4d.EventAdd()

    internal_create_job_bundle(
        save_dir,
        take_selection=TakeSelection.ALL,
        enable_tile_rendering=True,
        tiles_columns=2,
        tiles_rows=2,
    )


if __name__ == "__main__":
    main()
