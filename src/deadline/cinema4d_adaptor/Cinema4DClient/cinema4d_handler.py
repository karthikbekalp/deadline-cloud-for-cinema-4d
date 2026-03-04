# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
from __future__ import annotations

import os
import traceback
from typing import Any, Callable, Dict

try:
    import c4d  # type: ignore
    import maxon
    from c4d import bitmaps
except ImportError:  # pragma: no cover
    raise OSError("Could not find the Cinema4D module. Are you running this inside of Cinema4D?")

_RENDERRESULT = {
    c4d.RENDERRESULT_OK: "Function was successful.",
    c4d.RENDERRESULT_OUTOFMEMORY: "Not enough memory.",
    c4d.RENDERRESULT_ASSETMISSING: "Assets (textures etc.) are missing.",
    c4d.RENDERRESULT_SAVINGFAILED: "Failed to save.",
    c4d.RENDERRESULT_USERBREAK: "User stopped the processing.",
    c4d.RENDERRESULT_GICACHEMISSING: "GI cache is missing.",
    c4d.RENDERRESULT_NOMACHINE: "Machine was not found. (Team Rendering only)",
    c4d.RENDERRESULT_PROJECTNOTFOUND: "Project was not found.",
    c4d.RENDERRESULT_ERRORLOADINGPROJECT: "There was an error while loading the project.",
    c4d.RENDERRESULT_NOOUTPUTSPECIFIED: "Output was not specified.",
}

USE_CACHED_TEXT_KEY = "use_cached_text"
FRAME_KEY = "frame"
OUTPUT_PATH_KEY = "output_path"
MULTIPASS_PATH_KEY = "multi_pass_path"
SCENE_FILE_KEY = "scene_file"
START_RENDER_KEY = "start_render"
ASSEMBLE_TILES_KEY = "assemble_tiles"
TAKE_KEY = "take"


def progress_callback(progress_percent, progress_type_int):
    """Function passed in RenderDocument. It will be called automatically by Cinema 4D with the current render progress.

    Args:
        progress (float): The percent of the progress for the current step
        progress_type (c4d.RENDERPROGRESSTYPE): The Main part of the current rendering step
    """
    progress_type_map = {
        c4d.RENDERPROGRESSTYPE_BEFORERENDERING: "before rendering",
        c4d.RENDERPROGRESSTYPE_DURINGRENDERING: "during rendering",
        c4d.RENDERPROGRESSTYPE_AFTERRENDERING: "after rendering",
        c4d.RENDERPROGRESSTYPE_GLOBALILLUMINATION: "global illumination",
        c4d.RENDERPROGRESSTYPE_QUICK_PREVIEW: "quick preview",
        c4d.RENDERPROGRESSTYPE_AMBIENTOCCLUSION: "ambient occlusion",
    }
    if progress_type_int in progress_type_map:
        progress_type_text = progress_type_map[progress_type_int]
    else:
        progress_type_text = f"Unknown progress type ({progress_type_int})"

    print(f"Progress update ({progress_type_text}): {progress_percent * 100.0}%")

    if progress_type_int == c4d.RENDERPROGRESSTYPE_DURINGRENDERING:
        print("ALF_PROGRESS %g" % (progress_percent * 100))


class Cinema4DHandler:
    action_dict: Dict[str, Callable[[Dict[str, Any]], None]] = {}
    render_kwargs: Dict[str, Any]
    map_path: Callable[[str], str]

    C4D_FONT_INDEX = c4d.DescID(
        c4d.DescLevel(c4d.PRIM_TEXT_FONT, c4d.FONTCHOOSER_DATA, c4d.OBJECT_SPLINETEXT)
    )

    def __init__(self, map_path: Callable[[str], str]) -> None:
        """
        Constructor for the c4dpy handler. Initializes action_dict and render variables
        """
        self.action_dict = {
            SCENE_FILE_KEY: self.set_scene_file,
            TAKE_KEY: self.set_take,
            FRAME_KEY: self.set_frame,
            START_RENDER_KEY: self.start_render,
            ASSEMBLE_TILES_KEY: self.assemble_tiles,
            OUTPUT_PATH_KEY: self.output_path,
            MULTIPASS_PATH_KEY: self.multi_pass_path,
            USE_CACHED_TEXT_KEY: self.use_cached_text,
        }
        self.render_kwargs = {}
        self.take = "Main"
        self.map_path = map_path
        self.has_unmapped_pyro = False
        self.cached_text_was_used_in_previous_frame = False

    def _remap_assets(self) -> None:
        """
        Asset references in the .c4d files are not automatically re-mapped if they are
        absolute paths. This function remaps the asset references to the new paths.
        """
        asset_list: list[Dict[str, Any]] = []
        c4d.documents.GetAllAssetsNew(
            self.doc, allowDialogs=False, lastPath="", assetList=asset_list
        )
        for asset in asset_list:
            owner = asset.get("owner")
            param_id = asset.get("paramId")
            filename = asset.get("filename")
            node_space = asset.get("nodeSpace")
            node_path = asset.get("nodePath")
            if not (owner and param_id and filename):
                # unrelated asset, e.g. the main scene which is already pathmapped
                continue
            mapped_path = self.map_path(filename)
            # note: we can't skip if mapped_path == filename because some internal
            # references in the owner nodes may need to be updated

            # whether we have done owner[param_id] = mapped_path
            attempted_basic_path_mapping_approach = False
            try:
                success = self._pathmap_recognized_types(
                    owner, param_id, node_space, node_path, mapped_path
                )

                if not success:
                    print(
                        f"WARNING: asset wasn't recognized. Attempting to path map {owner}[{param_id}] = {mapped_path}"
                    )
                    attempted_basic_path_mapping_approach = True
                    owner[param_id] = mapped_path

            except Exception as e:
                print(
                    f"WARNING: asset with asset owner '{owner}', asset paramId {param_id}, filename "
                    f"'{filename}', nodeSpace '{node_space}', and nodePath '{node_path}' could not be path "
                    f"mapped. Error: {e} {traceback.format_exc()}"
                )
                if not attempted_basic_path_mapping_approach:
                    print(
                        f"Attempting to use basic path mapping {owner}[{param_id}] = {mapped_path}"
                    )
                    try:
                        owner[param_id] = mapped_path
                    except Exception as f:
                        print(
                            f"{owner}[{param_id}] = {mapped_path} failed. Error: {f} {traceback.format_exc()}"
                        )

        if self.has_unmapped_pyro:
            print(
                "Pyro elements were detected in the scene. If the pyro is not appearing in the "
                "output, the you can use one of the following approaches to resolve the issue:\n"
                " * Update the scene assets to use localized paths (Project Asset Inspector => [select all assets] => Asset => Localize Filenames)\n"
                " * Save the scene using 'Save Project with Assets'\n"
                " * Submit the scene with the 'Save Cinema 4D project with assets before submission' option"
            )

    def _pathmap_recognized_types(
        self, owner, param_id, node_space, node_path, mapped_path
    ) -> bool:
        """
        Applies path mapping to recognized owner types.

        Returns True if the owner is recognized and has been path mapped.
        Returns False otherwise.
        """
        if isinstance(owner, c4d.BaseShader):
            # C4D classic textures
            return self._pathmap_base_shader(owner, param_id, mapped_path)

        if isinstance(owner, c4d.BaseObject):
            # Redshift light textures
            return self._pathmap_base_object(owner, mapped_path)

        if isinstance(owner, c4d.documents.BaseVideoPost):
            # PostFX, e.g. LUT files or background files
            return self._pathmap_base_video_post(owner, mapped_path)

        if isinstance(owner, c4d.BaseMaterial):
            # Redshift node-based materials
            return self._pathmap_base_material(owner, node_space, node_path, mapped_path)

        return False

    def _pathmap_base_shader(self, owner, param_id, mapped_path) -> bool:
        # C4D classic materials have a param ID other than -1
        if param_id != -1:
            owner[param_id] = mapped_path
            return True
        return False

    def _pathmap_base_object(self, owner, mapped_path) -> bool:
        # c4d.BaseObject e.g. Redshift light texture
        mapped = False
        for item in [
            c4d.REDSHIFT_LIGHT_PHYSICAL_TEXTURE,
            c4d.REDSHIFT_LIGHT_DOME_TEX0,
            c4d.REDSHIFT_LIGHT_DOME_TEX1,
        ]:
            # there are three types of textures for Redshift lights.
            # For each type of texture, we check if the texture is specified,
            # and if it is, we override the path
            desc_id = c4d.DescID(
                # 1036765 is the data type for textures
                c4d.DescLevel(item, 1036765),
                c4d.DescLevel(c4d.REDSHIFT_FILE_PATH, c4d.DTYPE_STRING, 0),
            )
            existing_path = owner[desc_id]
            if existing_path:
                owner[desc_id] = mapped_path
                mapped = True

        if hasattr(c4d, "Opyro") and owner.GetType() == c4d.Opyro:
            # Opyro (i.e. Pyro output starting in C4D 2026) actually breaks if you try
            # to pathmap it, so we will simply return True to indicate that all applicable
            # pathmapping operations (i.e. none) are complete.
            self.has_unmapped_pyro = True
            return True

        return mapped

    def _pathmap_base_video_post(self, owner, mapped_path) -> bool:
        # PostFX, e.g. LUT files or background files
        path = owner[c4d.REDSHIFT_POSTEFFECTS_LUT_FILE]
        if path:
            owner[c4d.REDSHIFT_POSTEFFECTS_LUT_FILE] = mapped_path
            return True
        return False

    def _pathmap_base_material(self, owner, node_space, node_path, mapped_path) -> bool:
        # Redshift materials
        if not (node_path and node_space == "com.redshift3d.redshift4c4d.class.nodespace"):
            return False

        # Redshift node
        node_material = owner.GetNodeMaterialReference()
        graph = node_material.GetGraph(maxon.Id(node_space))
        with graph.BeginTransaction() as transaction:
            node = graph.GetNode(maxon.NodePath(node_path))
            node_id = node.GetId().ToString()
            if node_id.split("@")[0] == "texturesampler":
                path_port = (
                    node.GetInputs()
                    .FindChild("com.redshift3d.redshift4c4d.nodes.core.texturesampler.tex0")
                    .FindChild("path")
                )
                path_port.SetDefaultValue(mapped_path)
            else:
                print(f"Unrecognized nodeId {node_id}")
                return False
            transaction.Commit()
        return True

    def start_render(self, data: dict) -> None:
        if self.cached_text_was_used_in_previous_frame:
            # Close and then reload document since we collapsed some text in the previous frame
            # and it can no longer be animated.
            # Reloading the document will allow the next frame to have correct data.
            self._reload_document()

        self.render_data = self.doc.GetActiveRenderData()
        self.render_data[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_MANUAL
        self.render_kwargs[FRAME_KEY] = int(self.render_kwargs.get(FRAME_KEY, data[FRAME_KEY]))
        frame = self.render_kwargs[FRAME_KEY]
        fps = self.doc.GetFps()
        frame_time = c4d.BaseTime(frame, fps)
        self.render_data[c4d.RDATA_FRAMEFROM] = frame_time
        self.render_data[c4d.RDATA_FRAMETO] = frame_time
        self.render_data[c4d.RDATA_FRAMESTEP] = 1

        if self.render_data[c4d.RDATA_PATH]:
            self.render_data[c4d.RDATA_PATH] = self.map_path(self.render_data[c4d.RDATA_PATH])
        if (
            self.render_data[c4d.RDATA_MULTIPASS_SAVEIMAGE]
            and self.render_data[c4d.RDATA_MULTIPASS_FILENAME]
        ):
            self.render_data[c4d.RDATA_MULTIPASS_FILENAME] = self.map_path(
                self.render_data[c4d.RDATA_MULTIPASS_FILENAME]
            )

        # Apply tile render region if present
        # Tile data arrives as grid coordinates (current_tile_column, current_tile_row,
        # total_tiles_column, total_tiles_row).
        # We compute the normalized region and convert to pixel coordinates.
        is_tile_render = "total_tiles_column" in data
        tile_output_path = ""
        if is_tile_render:
            tiles_columns = int(data["total_tiles_column"])
            tiles_rows = int(data["total_tiles_row"])
            tile_col = int(data["current_tile_column"])
            tile_row = int(data["current_tile_row"])

            full_w = int(self.render_data[c4d.RDATA_XRES])
            full_h = int(self.render_data[c4d.RDATA_YRES])
            tile_w = full_w // tiles_columns
            tile_h = full_h // tiles_rows

            region_left = tile_col * tile_w
            region_top = tile_row * tile_h
            region_right = region_left + tile_w
            region_bottom = region_top + tile_h

            self.render_data[c4d.RDATA_RENDERREGION] = True
            self.render_data[c4d.RDATA_RENDERREGION_LEFT] = region_left
            self.render_data[c4d.RDATA_RENDERREGION_TOP] = region_top
            self.render_data[c4d.RDATA_RENDERREGION_RIGHT] = region_right
            self.render_data[c4d.RDATA_RENDERREGION_BOTTOM] = region_bottom

            # Save the mapped output paths for tile output.
            # We clear RDATA_PATH before RenderDocument so C4D doesn't save the
            # full-resolution beauty image (we crop and save it manually).
            # For multi-pass, we set RDATA_MULTIPASS_FILENAME to a tile-specific
            # path so C4D saves multi-pass layers natively — GetClonePart only
            # clones the beauty layer, so manual save would lose multi-pass data.
            tile_output_path = self.render_data[c4d.RDATA_PATH] or ""
            tile_multipass_path = self.render_data[c4d.RDATA_MULTIPASS_FILENAME] or ""
            self.render_data[c4d.RDATA_PATH] = ""

            # Build a tile-specific multi-pass path so C4D saves multi-pass natively.
            # We give C4D a base path WITHOUT frame number or extension — C4D's
            # native save appends its own frame numbering and format extension.
            # Including them here would cause a double frame suffix and a filename
            # mismatch at assembly time.
            if tile_multipass_path:
                mp_base, _mp_ext = os.path.splitext(tile_multipass_path)
                tile_mp_save_path = f"{mp_base}_tile_{tile_col}_{tile_row}"
                mp_output_dir = os.path.dirname(tile_mp_save_path)
                if mp_output_dir:
                    os.makedirs(mp_output_dir, exist_ok=True)
                self.render_data[c4d.RDATA_MULTIPASS_FILENAME] = tile_mp_save_path
            else:
                self.render_data[c4d.RDATA_MULTIPASS_FILENAME] = ""

        # Get the live render data instance — modifications here affect the document
        # directly, which is required for OCIO flags to take effect during rendering.
        rd = self.render_data.GetDataInstance()

        # OCIO handling: for 8-bit output, disable the render-time OCIO view transform
        # bake so we can bake it manually after rendering. This must be set on the live
        # render data instance (not a clone) for the flag to take effect.
        # See Maxon SDK open_color_io example: RenderOcioDocumentToPictureViewer.
        requires_baking = rd[c4d.RDATA_FORMATDEPTH] is c4d.RDATA_FORMATDEPTH_8
        orig_bake_flag = None
        print(
            f"OCIO: format_depth={rd[c4d.RDATA_FORMATDEPTH]}, requires_baking={requires_baking}, is_tile_render={is_tile_render}"
        )
        if is_tile_render and requires_baking:
            orig_bake_flag = rd.GetBool(c4d.RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER)
            rd[c4d.RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER] = False
            print(f"OCIO: disabled RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER (was {orig_bake_flag})")

        bm = bitmaps.MultipassBitmap(
            int(self.render_data[c4d.RDATA_XRES]),
            int(self.render_data[c4d.RDATA_YRES]),
            c4d.COLORMODE_RGBf,
        )
        bm.AddChannel(True, True)

        self.cached_text_was_used_in_previous_frame = self._cache_text_if_needed(frame_time)

        result = c4d.documents.RenderDocument(
            self.doc,
            rd,
            bm,
            c4d.RENDERFLAGS_EXTERNAL | c4d.RENDERFLAGS_SHOWERRORS,
            prog=progress_callback,
        )

        # Restore the OCIO bake flag to its original value
        if orig_bake_flag is not None:
            rd[c4d.RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER] = orig_bake_flag
            print(f"OCIO: restored RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER to {orig_bake_flag}")

        # Restore output paths so subsequent tile renders can use them
        if is_tile_render:
            if tile_output_path:
                self.render_data[c4d.RDATA_PATH] = tile_output_path
            if tile_multipass_path:
                self.render_data[c4d.RDATA_MULTIPASS_FILENAME] = tile_multipass_path
        result_description = _RENDERRESULT.get(result)
        if result_description is None:
            raise RuntimeError("Error: unhandled render result: %s" % result)
        if result != c4d.RENDERRESULT_OK:
            raise RuntimeError("Error: render result: %s" % result_description)

        # Bake OCIO view transform and null profiles for tile renders.
        # Following the Maxon SDK reference (open_color_io example):
        # - For 8-bit: bake the OCIO view transform into the bitmap, then null profiles
        # - For all depths: null display/view profiles to prevent double-application on save
        if is_tile_render:
            format_depth = rd[c4d.RDATA_FORMATDEPTH]
            print(
                f"OCIO: tile post-render — format_depth={format_depth}, requires_baking={requires_baking}"
            )
            print(
                f"OCIO: RDATA_FORMATDEPTH_8={c4d.RDATA_FORMATDEPTH_8}, match_is={format_depth is c4d.RDATA_FORMATDEPTH_8}, match_eq={format_depth == c4d.RDATA_FORMATDEPTH_8}"
            )
            print(f"OCIO: rendered bmp size={bm.GetBw()}x{bm.GetBh()}, bpp={bm.GetBt()}")

            # Sample a pixel from the rendered bitmap before any OCIO processing
            sample_x = region_left + tile_w // 2
            sample_y = region_top + tile_h // 2
            pre_bake_pixel = bm.GetPixel(sample_x, sample_y)
            print(f"OCIO: pre-bake sample pixel ({sample_x},{sample_y}): {pre_bake_pixel}")

            if requires_baking:
                baked = c4d.documents.BakeOcioViewToBitmap(bm, rd, c4d.SAVEBIT_NONE)
                print(f"OCIO: BakeOcioViewToBitmap returned {'a bitmap' if baked else 'None'}")
                bm = baked or bm
                post_bake_pixel = bm.GetPixel(sample_x, sample_y)
                print(f"OCIO: post-bake sample pixel ({sample_x},{sample_y}): {post_bake_pixel}")

            bm.SetColorProfile(c4d.bitmaps.ColorProfile(), c4d.COLORPROFILE_INDEX_DISPLAYSPACE)
            bm.SetColorProfile(c4d.bitmaps.ColorProfile(), c4d.COLORPROFILE_INDEX_VIEW_TRANSFORM)
            print("OCIO: nulled DISPLAYSPACE and VIEW_TRANSFORM color profiles")
            post_null_pixel = bm.GetPixel(sample_x, sample_y)
            print(
                f"OCIO: post-null-profiles sample pixel ({sample_x},{sample_y}): {post_null_pixel}"
            )

            # Determine save bit flags based on format depth
            if format_depth is c4d.RDATA_FORMATDEPTH_16:
                save_bits = c4d.SAVEBIT_16BITCHANNELS
            elif format_depth is c4d.RDATA_FORMATDEPTH_32:
                save_bits = c4d.SAVEBIT_32BITCHANNELS
            else:
                save_bits = c4d.SAVEBIT_NONE

        # Crop the tile region from the full bitmap using GetClonePart to preserve
        # bit depth and float data (GetPixel/SetPixel truncates to 8-bit integers).
        if is_tile_render:
            tile_bmp = bm.GetClonePart(region_left, region_top, tile_w, tile_h)
            if tile_bmp is None:
                raise RuntimeError(
                    f"Failed to crop tile ({tile_col}, {tile_row}) from rendered bitmap"
                )
            crop_sample = tile_bmp.GetPixel(tile_w // 2, tile_h // 2)
            print(
                f"OCIO: cropped tile via GetClonePart — tile size={tile_bmp.GetBw()}x{tile_bmp.GetBh()}, bit depth={tile_bmp.GetBt()}"
            )
            print(f"OCIO: cropped tile center pixel ({tile_w // 2},{tile_h // 2}): {crop_sample}")

            # Determine file extension from render format setting
            format_id = self.render_data[c4d.RDATA_FORMAT]
            format_map = {
                c4d.FILTER_PNG: (".png", c4d.FILTER_PNG),
                c4d.FILTER_JPG: (".jpg", c4d.FILTER_JPG),
                c4d.FILTER_TIF: (".tif", c4d.FILTER_TIF),
                c4d.FILTER_BMP: (".bmp", c4d.FILTER_BMP),
                c4d.FILTER_EXR: (".exr", c4d.FILTER_EXR),
                c4d.FILTER_HDR: (".hdr", c4d.FILTER_HDR),
                c4d.FILTER_PSD: (".psd", c4d.FILTER_PSD),
                c4d.FILTER_TGA: (".tga", c4d.FILTER_TGA),
            }
            ext, save_filter = format_map.get(format_id, (".png", c4d.FILTER_PNG))
            ext_to_filter = {v[0]: v[1] for v in format_map.values()}

            if tile_output_path:
                # Ensure the output directory exists
                output_dir = os.path.dirname(tile_output_path)
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)

                base, existing_ext = os.path.splitext(tile_output_path)
                if not existing_ext:
                    tile_path = f"{base}_{frame}_tile_{tile_col}_{tile_row}{ext}"
                    tile_save_filter = save_filter
                else:
                    tile_path = f"{base}_{frame}_tile_{tile_col}_{tile_row}{existing_ext}"
                    tile_save_filter = ext_to_filter.get(existing_ext.lower(), save_filter)

                tile_bmp.Save(tile_path, tile_save_filter, c4d.BaseContainer(), save_bits)
                print(f"Saved cropped tile ({tile_w}x{tile_h}) to {tile_path}")

            if tile_multipass_path:
                print(f"Multi-pass tile saved natively by C4D to tile ({tile_col}, {tile_row})")

        print("Finished Rendering")

    def assemble_tiles(self, data: dict) -> None:
        """Assemble tile images into a single full-resolution image using C4D's BaseBitmap."""
        tiles_columns = int(data["total_tiles_column"])
        tiles_rows = int(data["total_tiles_row"])
        frame = int(data["frame"])
        output_path = data.get("output_path", "")
        multi_pass_path = data.get("multi_pass_path", "")

        if not output_path:
            raise RuntimeError("assemble_tiles: no output_path provided")

        output_path = self.map_path(output_path)
        if multi_pass_path:
            multi_pass_path = self.map_path(multi_pass_path)

        # Determine extension and save filter from the document's render format
        render_data = self.doc.GetActiveRenderData()
        format_id = render_data[c4d.RDATA_FORMAT] if render_data else 0
        format_map = {
            c4d.FILTER_PNG: (".png", c4d.FILTER_PNG),
            c4d.FILTER_JPG: (".jpg", c4d.FILTER_JPG),
            c4d.FILTER_TIF: (".tif", c4d.FILTER_TIF),
            c4d.FILTER_BMP: (".bmp", c4d.FILTER_BMP),
            c4d.FILTER_EXR: (".exr", c4d.FILTER_EXR),
            c4d.FILTER_HDR: (".hdr", c4d.FILTER_HDR),
            c4d.FILTER_PSD: (".psd", c4d.FILTER_PSD),
            c4d.FILTER_TGA: (".tga", c4d.FILTER_TGA),
        }
        ext, save_filter = format_map.get(format_id, (".png", c4d.FILTER_PNG))

        base, existing_ext = os.path.splitext(output_path)
        if not existing_ext:
            existing_ext = ext

        # Load the first tile to determine tile dimensions
        first_tile_path = f"{base}_{frame}_tile_0_0{existing_ext}"
        first_tile = c4d.bitmaps.BaseBitmap()
        result = first_tile.InitWith(first_tile_path)
        if result[0] != c4d.IMAGERESULT_OK:
            raise RuntimeError(f"assemble_tiles: failed to load first tile: {first_tile_path}")

        tile_w = first_tile.GetBw()
        tile_h = first_tile.GetBh()
        tile_bpp = first_tile.GetBt()
        full_w = tile_w * tiles_columns
        full_h = tile_h * tiles_rows

        print(f"[assemble_tiles] first tile: {first_tile_path}")
        print(f"[assemble_tiles] tile size: {tile_w}x{tile_h}, bpp: {tile_bpp}")
        print(f"[assemble_tiles] final size: {full_w}x{full_h}")
        print(f"[assemble_tiles] grid: {tiles_columns}x{tiles_rows}, frame: {frame}")

        # Determine color mode and bytes-per-pixel based on bit depth.
        # GetPixelCnt/SetPixelCnt preserve full bit depth unlike GetPixel/SetPixel.
        bpc = tile_bpp // 3  # bits per channel
        if bpc == 32:
            color_mode = c4d.COLORMODE_RGBf
            inc = 12  # 3 channels * 4 bytes (float)
        elif bpc == 16:
            color_mode = c4d.COLORMODE_RGBw
            inc = 6  # 3 channels * 2 bytes
        else:
            color_mode = c4d.COLORMODE_RGB
            inc = 3  # 3 channels * 1 byte

        print(f"[assemble_tiles] bits per channel: {bpc}, color_mode: {color_mode}, inc: {inc}")

        # Create the full-resolution output bitmap matching tile bit depth
        final_bmp = c4d.bitmaps.BaseBitmap()
        final_bmp.Init(full_w, full_h, depth=tile_bpp)
        print(
            f"[assemble_tiles] final_bmp initialized: {final_bmp.GetBw()}x{final_bmp.GetBh()}, bpp: {final_bmp.GetBt()}"
        )

        # Reusable buffer for one row of tile pixels
        row_buffer = bytearray(tile_w * inc)
        row_view = memoryview(row_buffer)

        for row in range(tiles_rows):
            for col in range(tiles_columns):
                tile_path = f"{base}_{frame}_tile_{col}_{row}{existing_ext}"
                tile_bmp = c4d.bitmaps.BaseBitmap()
                load_result = tile_bmp.InitWith(tile_path)
                if load_result[0] != c4d.IMAGERESULT_OK:
                    raise RuntimeError(f"assemble_tiles: failed to load tile: {tile_path}")

                loaded_w = tile_bmp.GetBw()
                loaded_h = tile_bmp.GetBh()
                loaded_bpp = tile_bmp.GetBt()
                print(f"[assemble_tiles] tile ({col},{row}): {tile_path}")
                print(f"[assemble_tiles]   loaded size: {loaded_w}x{loaded_h}, bpp: {loaded_bpp}")

                # Sample a pixel from the tile for comparison
                sample_pixel = tile_bmp.GetPixel(0, 0)
                print(f"[assemble_tiles]   tile sample pixel (0,0): {sample_pixel}")

                # Copy tile row-by-row into the final bitmap at the correct offset
                dst_x = col * tile_w
                dst_y = row * tile_h
                print(f"[assemble_tiles]   writing to dst_x={dst_x}, dst_y={dst_y}")
                for py in range(tile_h):
                    tile_bmp.GetPixelCnt(0, py, tile_w, row_view, inc, color_mode, c4d.PIXELCNT_0)
                    final_bmp.SetPixelCnt(
                        dst_x, dst_y + py, tile_w, row_view, inc, color_mode, c4d.PIXELCNT_0
                    )

                # Verify: read back the same pixel from the final bitmap
                verify_pixel = final_bmp.GetPixel(dst_x, dst_y)
                print(f"[assemble_tiles]   final verify pixel ({dst_x},{dst_y}): {verify_pixel}")

                print(f"Assembled tile ({col}, {row}) from {tile_path}")

        # Save the assembled image
        final_path = f"{base}_{frame}{existing_ext}"
        output_dir = os.path.dirname(final_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        # Null color profiles to prevent C4D from applying an OCIO/color transform
        # on save. The tile images already have the correct color baked in — without
        # this, the assembled image gets a double gamma application and looks darker.
        # Copy the color profile from the first tile (which was saved correctly) to
        # ensure the assembled image uses the same profile.
        first_tile_profile = first_tile.GetColorProfile()
        if first_tile_profile is not None:
            final_bmp.SetColorProfile(first_tile_profile)
            print("[assemble_tiles] copied color profile from first tile")
        else:
            final_bmp.SetColorProfile(
                c4d.bitmaps.ColorProfile(), c4d.COLORPROFILE_INDEX_DISPLAYSPACE
            )
            final_bmp.SetColorProfile(
                c4d.bitmaps.ColorProfile(), c4d.COLORPROFILE_INDEX_VIEW_TRANSFORM
            )
            print("[assemble_tiles] nulled color profiles on final bitmap (no tile profile found)")

        ext_to_filter = {v[0]: v[1] for v in format_map.values()}
        final_filter = ext_to_filter.get(existing_ext.lower(), save_filter)
        print(f"[assemble_tiles] saving to: {final_path}")
        print(f"[assemble_tiles] save filter: {final_filter}, ext: {existing_ext}")
        final_bmp.Save(final_path, final_filter)
        print(f"Assembled {tiles_columns * tiles_rows} tiles into {final_path} ({full_w}x{full_h})")

        # Assemble multi-pass tiles if multi_pass_path is provided.
        # Multi-pass tiles are saved by C4D at full resolution (with only the tile
        # region rendered). We extract each tile's region and composite them.
        # In start_render we set RDATA_MULTIPASS_FILENAME to a base path like
        # "{mp_base}_tile_{col}_{row}" (no frame number or extension). C4D's native
        # save appends "_{frame:04d}" and the format extension determined by the
        # multi-pass format setting (RDATA_MULTIPASS_SAVEFORMAT), e.g.
        # "{mp_base}_tile_0_0_0150.psd".
        if multi_pass_path:
            mp_base, mp_ext = os.path.splitext(multi_pass_path)
            if not mp_ext:
                # Determine extension from the multi-pass save format setting
                mp_format_id = render_data[c4d.RDATA_MULTIPASS_SAVEFORMAT] if render_data else 0
                mp_ext = format_map.get(mp_format_id, (".png", c4d.FILTER_PNG))[0]
            padded_frame = str(frame).zfill(4)

            # Load the first multi-pass tile to get dimensions
            first_mp_path = f"{mp_base}_tile_0_0_{padded_frame}{mp_ext}"
            print(f"[assemble_tiles] looking for first multi-pass tile: {first_mp_path}")
            first_mp = c4d.bitmaps.BaseBitmap()
            mp_result = first_mp.InitWith(first_mp_path)
            if mp_result[0] != c4d.IMAGERESULT_OK:
                print(
                    f"[assemble_tiles] WARNING: failed to load first multi-pass tile: {first_mp_path}, skipping multi-pass assembly"
                )
            else:
                mp_full_w = first_mp.GetBw()
                mp_full_h = first_mp.GetBh()
                mp_tile_w = mp_full_w // tiles_columns
                mp_tile_h = mp_full_h // tiles_rows
                mp_bpp = first_mp.GetBt()
                mp_bpc = mp_bpp // 3

                if mp_bpc == 32:
                    mp_color_mode = c4d.COLORMODE_RGBf
                    mp_inc = 12
                elif mp_bpc == 16:
                    mp_color_mode = c4d.COLORMODE_RGBw
                    mp_inc = 6
                else:
                    mp_color_mode = c4d.COLORMODE_RGB
                    mp_inc = 3

                mp_final = c4d.bitmaps.BaseBitmap()
                mp_final.Init(mp_full_w, mp_full_h, depth=mp_bpp)
                mp_row_buffer = bytearray(mp_tile_w * mp_inc)
                mp_row_view = memoryview(mp_row_buffer)

                print(
                    f"[assemble_tiles] assembling multi-pass: {mp_full_w}x{mp_full_h}, tile size: {mp_tile_w}x{mp_tile_h}"
                )

                for row in range(tiles_rows):
                    for col in range(tiles_columns):
                        mp_tile_path = f"{mp_base}_tile_{col}_{row}_{padded_frame}{mp_ext}"
                        mp_tile_bmp = c4d.bitmaps.BaseBitmap()
                        mp_load = mp_tile_bmp.InitWith(mp_tile_path)
                        if mp_load[0] != c4d.IMAGERESULT_OK:
                            print(
                                f"[assemble_tiles] WARNING: failed to load multi-pass tile: {mp_tile_path}"
                            )
                            continue

                        # Extract the tile region from the full-res multi-pass file
                        src_x = col * mp_tile_w
                        src_y = row * mp_tile_h
                        for py in range(mp_tile_h):
                            mp_tile_bmp.GetPixelCnt(
                                src_x,
                                src_y + py,
                                mp_tile_w,
                                mp_row_view,
                                mp_inc,
                                mp_color_mode,
                                c4d.PIXELCNT_0,
                            )
                            mp_final.SetPixelCnt(
                                src_x,
                                src_y + py,
                                mp_tile_w,
                                mp_row_view,
                                mp_inc,
                                mp_color_mode,
                                c4d.PIXELCNT_0,
                            )
                        print(f"[assemble_tiles] assembled multi-pass tile ({col}, {row})")

                mp_final_path = f"{mp_base}_{frame}{mp_ext}"
                mp_out_dir = os.path.dirname(mp_final_path)
                if mp_out_dir:
                    os.makedirs(mp_out_dir, exist_ok=True)

                # Copy color profile from first tile
                mp_profile = first_mp.GetColorProfile()
                if mp_profile is not None:
                    mp_final.SetColorProfile(mp_profile)

                mp_final_filter = ext_to_filter.get(mp_ext.lower(), save_filter)
                mp_final.Save(mp_final_path, mp_final_filter)
                print(
                    f"Assembled multi-pass {tiles_columns * tiles_rows} tiles into {mp_final_path}"
                )

        print("Finished Rendering")

    def output_path(self, data: dict) -> None:
        output_path = data.get(OUTPUT_PATH_KEY, "")
        self.render_kwargs[OUTPUT_PATH_KEY] = output_path
        if output_path:
            doc = c4d.documents.GetActiveDocument()
            render_data = doc.GetActiveRenderData()
            render_data[c4d.RDATA_PATH] = self.map_path(output_path)

    def multi_pass_path(self, data: dict) -> None:
        multi_pass_path = data.get(MULTIPASS_PATH_KEY, "")
        self.render_kwargs[MULTIPASS_PATH_KEY] = multi_pass_path
        if multi_pass_path:
            doc = c4d.documents.GetActiveDocument()
            render_data = doc.GetActiveRenderData()
            render_data[c4d.RDATA_MULTIPASS_FILENAME] = self.map_path(multi_pass_path)

    def set_take(self, data: dict) -> None:
        """
        Sets the take to render

        Args:
            data (dict):
        """
        take_name = data.get(TAKE_KEY, "")
        self.render_kwargs[TAKE_KEY] = take_name
        doc = c4d.documents.GetActiveDocument()
        take_data = doc.GetTakeData()
        if not take_data:
            return

        def get_child_takes(take):
            child_takes = take.GetChildren()
            all_takes = child_takes
            if child_takes:
                for child_take in child_takes:
                    all_takes.extend(get_child_takes(child_take))
            return all_takes

        main_take = take_data.GetCurrentTake()
        all_takes = [main_take] + get_child_takes(main_take)

        take = None
        for take in all_takes:
            if take.GetName() == take_name:
                break
        if take is None:
            print("Error: take not found: %s" % take_name)
        take_data.SetCurrentTake(take)

    def use_cached_text(self, data: dict) -> None:
        """
        Sets whether text should be cached on Linux

        Args:
            data (dict): the data of whether to cache the text in the format {USE_CACHED_TEXT_KEY: bool}
        """
        self.render_kwargs[USE_CACHED_TEXT_KEY] = bool(int(data.get(USE_CACHED_TEXT_KEY, 0)))

    def set_frame(self, data: dict) -> None:
        """
        Sets the frame to render

        Args:
            data (dict):
        """
        self.render_kwargs[FRAME_KEY] = int(data[FRAME_KEY])

    def set_scene_file(self, data: dict) -> None:
        """
        Opens the scene file in Cinema4D.

        Args:
            data (dict): The data given from the Adaptor. Keys expected: ['scene_file']

        Raises:
            FileNotFoundError: If path to the scene file does not yield a file
        """
        scene_file = data.get(SCENE_FILE_KEY, "")
        self.render_kwargs[SCENE_FILE_KEY] = data[SCENE_FILE_KEY]
        if not os.path.isfile(scene_file):
            raise FileNotFoundError(f"The scene file '{scene_file}' does not exist")
        doc = c4d.documents.LoadDocument(
            scene_file, c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS
        )
        if doc is None:
            print("Error: LoadDocument failed: %s" % scene_file)
        else:
            # Build animations, caches and expressions for all frames in the document.
            # This is essential for dynamic content like Pyro simulations (fluid/smoke effects)
            # which would otherwise render as blank. The parameters ensure all necessary
            # elements (animation, expressions, caches) are processed.
            doc.ExecutePasses(
                bt=None, animation=True, expressions=True, caches=True, flags=c4d.BUILDFLAGS_NONE
            )

            c4d.documents.InsertBaseDocument(doc)
            c4d.documents.SetActiveDocument(doc)
            self.doc = doc
            self._remap_assets()

    def _has_cached_text(self, objects: list[Any]) -> bool:
        for obj in objects:
            font_container = obj[self.C4D_FONT_INDEX]
            font = font_container.GetFont()
            if font:
                return True
            children = obj.GetChildren()
            if children and self._has_cached_text(children):
                return True
        return False

    def _get_all_text_objects(self, objects: list[Any]) -> list[Any]:
        """
        Retrieves all text objects in the scene. They will be listed with
        all children objects AFTER (higher index in the list than) their parent objects.
        """
        text_objects = []
        for obj in objects:
            font_container = obj[self.C4D_FONT_INDEX]
            font = font_container.GetFont()
            if font:
                text_objects.append(obj)
            # all objects, including text itself, can have nested text objects that also need to be cached
            children = obj.GetChildren()
            if children:
                text_objects += self._get_all_text_objects(children)

        return text_objects

    def _cache_text_if_needed(self, frame_time: c4d.BaseTime) -> bool:
        """
        On cross-platform submissions, Cinema 4D sometimes handles fonts incorrectly.

        To work around this, the user can select the `Use cached text during render` option in the submitter
        This will convert the text to polygons for each frame, rather than procedurally generating text.

        This option is most often used on Linux, which doesn't support procedural font rendering.
        However, it is also relevant to cross-platform submissions from Mac -> Windows.

        If text caching is needed, this function will cache the text. Otherwise, it is a no-op.

        Returns True if text has been cached. Returns False otherwise.
        """
        if (
            USE_CACHED_TEXT_KEY not in self.render_kwargs
            or not self.render_kwargs[USE_CACHED_TEXT_KEY]
        ):
            print(
                "If you see incorrect fonts or missing text, try the 'Use cached text during render' option "
                "under 'Job-specific settings' in the submitter."
            )
            return False

        found_font = self._has_cached_text(self.doc.GetObjects())

        if not found_font:
            print("No fonts were found in the scene, no need to cache text.")
            return False

        print("Fonts were found in the scene")

        print("Setting the correct frame/time to determine text location.")
        c4d.documents.SetDocumentTime(self.doc, frame_time)

        print(f"Animating the text for frame {self.render_kwargs[FRAME_KEY]}.")
        self.doc.ExecutePasses(
            bt=None, animation=True, expressions=True, caches=True, flags=c4d.BUILDFLAGS_NONE
        )
        print("The location of the text was recalculated. Refreshing the text object list.")

        # we do this a second time in case objects are recalculated and have different references
        text_objects = self._get_all_text_objects(self.doc.GetObjects())

        if not text_objects:
            print("No text objects were found in the scene after animation.")
            return False

        print(f"Text objects found in scene after animation: {text_objects}")

        # The _get_all_text_objects() function returns all text objects with the parent objects first, then children
        # objects. However, in the modeling command below, we actually need to list the children objects before the
        # parent objects so that each object reference remains valid when modified in order.
        #
        # For example, if there is parent text and child text, and the parent text is made editable (converted to
        # polygons) first, then the child reference will no longer be valid. This breaks the child reference and causes
        # a segmentation fault.
        # However, if we convert the child text to polygons first, the parent text will still be valid and can be converted
        # to polygons as well.
        text_objects.reverse()

        print("Converting all parameterized text objects to polygons for correct rendering.")
        c4d.utils.SendModelingCommand(
            command=c4d.MCOMMAND_MAKEEDITABLE,  # convert the cached parameterized text to polygons
            list=text_objects,
            mode=c4d.MODELINGCOMMANDMODE_ALL,  # apply to all points/polygons
            doc=self.doc,
            flags=c4d.MODELINGCOMMANDFLAGS_CREATEUNDO,  # apply to the current document
        )
        print("Successfully converted all text objects to polygons.")

        return True

    def _reload_document(self) -> None:
        c4d.documents.KillDocument(c4d.documents.GetActiveDocument())
        for action in [SCENE_FILE_KEY, TAKE_KEY, OUTPUT_PATH_KEY, MULTIPASS_PATH_KEY]:
            if action in self.render_kwargs:
                self.action_dict[action]({action: self.render_kwargs[action]})
