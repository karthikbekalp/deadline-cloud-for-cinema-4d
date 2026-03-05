# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

try:
    import c4d  # type: ignore
    from c4d import bitmaps
except ImportError:  # pragma: no cover
    raise OSError("Could not find the Cinema4D module. Are you running this inside of Cinema4D?")


# Shared format map: render format ID -> (extension, save filter)
FORMAT_MAP = {
    c4d.FILTER_PNG: (".png", c4d.FILTER_PNG),
    c4d.FILTER_JPG: (".jpg", c4d.FILTER_JPG),
    c4d.FILTER_TIF: (".tif", c4d.FILTER_TIF),
    c4d.FILTER_BMP: (".bmp", c4d.FILTER_BMP),
    c4d.FILTER_EXR: (".exr", c4d.FILTER_EXR),
    c4d.FILTER_HDR: (".hdr", c4d.FILTER_HDR),
    c4d.FILTER_PSD: (".psd", c4d.FILTER_PSD),
    c4d.FILTER_TGA: (".tga", c4d.FILTER_TGA),
}

EXT_TO_FILTER = {v[0]: v[1] for v in FORMAT_MAP.values()}


def get_format_info(format_id: int) -> tuple[str, int]:
    """Return (extension, save_filter) for a C4D render format ID."""
    return FORMAT_MAP.get(format_id, (".png", c4d.FILTER_PNG))


def determine_color_mode(bpp: int) -> tuple[int, int]:
    """Determine C4D color mode and bytes-per-pixel increment from bits-per-pixel.

    Returns:
        (color_mode, inc) where inc is bytes per pixel for GetPixelCnt/SetPixelCnt.
    """
    bpc = bpp // 3  # bits per channel
    if bpc == 32:
        return c4d.COLORMODE_RGBf, 12  # 3 channels * 4 bytes (float)
    elif bpc == 16:
        return c4d.COLORMODE_RGBw, 6  # 3 channels * 2 bytes
    else:
        return c4d.COLORMODE_RGB, 3  # 3 channels * 1 byte


def determine_save_bits(format_depth: int) -> int:
    """Return the SAVEBIT flags appropriate for the given RDATA_FORMATDEPTH."""
    if format_depth is c4d.RDATA_FORMATDEPTH_16:
        return c4d.SAVEBIT_16BITCHANNELS
    elif format_depth is c4d.RDATA_FORMATDEPTH_32:
        return c4d.SAVEBIT_32BITCHANNELS
    else:
        return c4d.SAVEBIT_NONE


@dataclass
class TileContext:
    """Holds tile render state between setup and finalize phases."""

    tile_col: int
    tile_row: int
    tiles_columns: int
    tiles_rows: int
    tile_w: int
    tile_h: int
    region_left: int
    region_top: int
    region_right: int
    region_bottom: int
    tile_output_path: str
    tile_multipass_path: str
    orig_bake_flag: Any
    requires_baking: bool
    save_bits: int


def setup_tile_render(
    render_data: Any,
    data: dict,
) -> TileContext:
    """Configure render data for tile rendering and return a TileContext.

    Sets the render region on render_data, adjusts output paths for tile saving,
    and computes all values needed for post-render finalization.

    Args:
        render_data: The active C4D render data object.
        data: The action data dict containing tile grid coordinates.

    Returns:
        A TileContext with all state needed by finalize_tile_render.
    """
    tiles_columns = int(data["total_tiles_column"])
    tiles_rows = int(data["total_tiles_row"])
    tile_col = int(data["current_tile_column"])
    tile_row = int(data["current_tile_row"])

    full_w = int(render_data[c4d.RDATA_XRES])
    full_h = int(render_data[c4d.RDATA_YRES])
    tile_w = full_w // tiles_columns
    tile_h = full_h // tiles_rows

    region_left = tile_col * tile_w
    region_top = tile_row * tile_h
    region_right = region_left + tile_w
    region_bottom = region_top + tile_h

    render_data[c4d.RDATA_RENDERREGION] = True
    render_data[c4d.RDATA_RENDERREGION_LEFT] = region_left
    render_data[c4d.RDATA_RENDERREGION_TOP] = region_top
    render_data[c4d.RDATA_RENDERREGION_RIGHT] = region_right
    render_data[c4d.RDATA_RENDERREGION_BOTTOM] = region_bottom

    # Save original output paths — we clear RDATA_PATH so C4D doesn't save the
    # full-resolution beauty image (we crop and save it manually).
    # For multi-pass, we set a tile-specific path so C4D saves multi-pass natively.
    tile_output_path = render_data[c4d.RDATA_PATH] or ""
    tile_multipass_path = render_data[c4d.RDATA_MULTIPASS_FILENAME] or ""
    render_data[c4d.RDATA_PATH] = ""

    # Build a tile-specific multi-pass path — C4D's native save appends its own
    # frame numbering and format extension.
    if tile_multipass_path:
        mp_base, _mp_ext = os.path.splitext(tile_multipass_path)
        tile_mp_save_path = f"{mp_base}_tile_{tile_col}_{tile_row}"
        mp_output_dir = os.path.dirname(tile_mp_save_path)
        if mp_output_dir:
            os.makedirs(mp_output_dir, exist_ok=True)
        render_data[c4d.RDATA_MULTIPASS_FILENAME] = tile_mp_save_path
    else:
        render_data[c4d.RDATA_MULTIPASS_FILENAME] = ""

    # OCIO: for 8-bit output during tile renders, disable the render-time OCIO view
    # transform bake so we can bake it manually after rendering.
    rd = render_data.GetDataInstance()
    requires_baking = rd[c4d.RDATA_FORMATDEPTH] is c4d.RDATA_FORMATDEPTH_8
    orig_bake_flag = None
    print(
        f"OCIO: format_depth={rd[c4d.RDATA_FORMATDEPTH]}, requires_baking={requires_baking}"
    )
    if requires_baking:
        orig_bake_flag = rd.GetBool(c4d.RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER)
        rd[c4d.RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER] = False
        print(f"OCIO: disabled RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER (was {orig_bake_flag})")

    save_bits = determine_save_bits(rd[c4d.RDATA_FORMATDEPTH])

    return TileContext(
        tile_col=tile_col,
        tile_row=tile_row,
        tiles_columns=tiles_columns,
        tiles_rows=tiles_rows,
        tile_w=tile_w,
        tile_h=tile_h,
        region_left=region_left,
        region_top=region_top,
        region_right=region_right,
        region_bottom=region_bottom,
        tile_output_path=tile_output_path,
        tile_multipass_path=tile_multipass_path,
        orig_bake_flag=orig_bake_flag,
        requires_baking=requires_baking,
        save_bits=save_bits,
    )


def finalize_tile_render(
    bm: Any,
    rd: Any,
    ctx: TileContext,
    render_data: Any,
    frame: int,
) -> None:
    """Post-render processing for a tile: OCIO bake, crop, save, and restore paths.

    Args:
        bm: The rendered MultipassBitmap.
        rd: The live render data instance (from GetDataInstance).
        ctx: The TileContext from setup_tile_render.
        render_data: The render data object (to restore output paths).
        frame: The current frame number.
    """
    # Restore the OCIO bake flag to its original value
    if ctx.orig_bake_flag is not None:
        rd[c4d.RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER] = ctx.orig_bake_flag
        print(f"OCIO: restored RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER to {ctx.orig_bake_flag}")

    format_depth = rd[c4d.RDATA_FORMATDEPTH]
    print(
        f"OCIO: tile post-render — format_depth={format_depth}, requires_baking={ctx.requires_baking}"
    )
    print(
        f"OCIO: RDATA_FORMATDEPTH_8={c4d.RDATA_FORMATDEPTH_8}, match_is={format_depth is c4d.RDATA_FORMATDEPTH_8}, match_eq={format_depth == c4d.RDATA_FORMATDEPTH_8}"
    )
    print(f"OCIO: rendered bmp size={bm.GetBw()}x{bm.GetBh()}, bpp={bm.GetBt()}")

    # Sample a pixel from the rendered bitmap before any OCIO processing
    sample_x = ctx.region_left + ctx.tile_w // 2
    sample_y = ctx.region_top + ctx.tile_h // 2
    pre_bake_pixel = bm.GetPixel(sample_x, sample_y)
    print(f"OCIO: pre-bake sample pixel ({sample_x},{sample_y}): {pre_bake_pixel}")

    if ctx.requires_baking:
        baked = c4d.documents.BakeOcioViewToBitmap(bm, rd, c4d.SAVEBIT_NONE)
        print(f"OCIO: BakeOcioViewToBitmap returned {'a bitmap' if baked else 'None'}")
        bm = baked or bm
        post_bake_pixel = bm.GetPixel(sample_x, sample_y)
        print(f"OCIO: post-bake sample pixel ({sample_x},{sample_y}): {post_bake_pixel}")

    bm.SetColorProfile(c4d.bitmaps.ColorProfile(), c4d.COLORPROFILE_INDEX_DISPLAYSPACE)
    bm.SetColorProfile(c4d.bitmaps.ColorProfile(), c4d.COLORPROFILE_INDEX_VIEW_TRANSFORM)
    print("OCIO: nulled DISPLAYSPACE and VIEW_TRANSFORM color profiles")
    post_null_pixel = bm.GetPixel(sample_x, sample_y)
    print(f"OCIO: post-null-profiles sample pixel ({sample_x},{sample_y}): {post_null_pixel}")

    # Crop the tile region from the full bitmap using GetClonePart to preserve
    # bit depth and float data (GetPixel/SetPixel truncates to 8-bit integers).
    tile_bmp = bm.GetClonePart(ctx.region_left, ctx.region_top, ctx.tile_w, ctx.tile_h)
    if tile_bmp is None:
        raise RuntimeError(
            f"Failed to crop tile ({ctx.tile_col}, {ctx.tile_row}) from rendered bitmap"
        )
    crop_sample = tile_bmp.GetPixel(ctx.tile_w // 2, ctx.tile_h // 2)
    print(
        f"OCIO: cropped tile via GetClonePart — tile size={tile_bmp.GetBw()}x{tile_bmp.GetBh()}, bit depth={tile_bmp.GetBt()}"
    )
    print(f"OCIO: cropped tile center pixel ({ctx.tile_w // 2},{ctx.tile_h // 2}): {crop_sample}")

    # Determine file extension from render format setting
    format_id = render_data[c4d.RDATA_FORMAT]
    ext, save_filter = get_format_info(format_id)

    if ctx.tile_output_path:
        output_dir = os.path.dirname(ctx.tile_output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        base, existing_ext = os.path.splitext(ctx.tile_output_path)
        if not existing_ext:
            tile_path = f"{base}_{frame}_tile_{ctx.tile_col}_{ctx.tile_row}{ext}"
            tile_save_filter = save_filter
        else:
            tile_path = f"{base}_{frame}_tile_{ctx.tile_col}_{ctx.tile_row}{existing_ext}"
            tile_save_filter = EXT_TO_FILTER.get(existing_ext.lower(), save_filter)

        tile_bmp.Save(tile_path, tile_save_filter, c4d.BaseContainer(), ctx.save_bits)
        print(f"Saved cropped tile ({ctx.tile_w}x{ctx.tile_h}) to {tile_path}")

    if ctx.tile_multipass_path:
        print(f"Multi-pass tile saved natively by C4D to tile ({ctx.tile_col}, {ctx.tile_row})")

    # Restore output paths so subsequent tile renders can use them
    if ctx.tile_output_path:
        render_data[c4d.RDATA_PATH] = ctx.tile_output_path
    if ctx.tile_multipass_path:
        render_data[c4d.RDATA_MULTIPASS_FILENAME] = ctx.tile_multipass_path


def _assemble_beauty_tiles(
    base: str,
    existing_ext: str,
    frame: int,
    tiles_columns: int,
    tiles_rows: int,
    save_filter: int,
) -> None:
    """Assemble beauty pass tile images into a single full-resolution image.

    Args:
        base: The output path stem (without extension).
        existing_ext: The file extension to use.
        frame: The current frame number.
        tiles_columns: Number of tile columns.
        tiles_rows: Number of tile rows.
        save_filter: The C4D save filter ID.
    """
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

    color_mode, inc = determine_color_mode(tile_bpp)
    print(
        f"[assemble_tiles] bits per channel: {tile_bpp // 3}, color_mode: {color_mode}, inc: {inc}"
    )

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

            sample_pixel = tile_bmp.GetPixel(0, 0)
            print(f"[assemble_tiles]   tile sample pixel (0,0): {sample_pixel}")

            dst_x = col * tile_w
            dst_y = row * tile_h
            print(f"[assemble_tiles]   writing to dst_x={dst_x}, dst_y={dst_y}")
            for py in range(tile_h):
                tile_bmp.GetPixelCnt(0, py, tile_w, row_view, inc, color_mode, c4d.PIXELCNT_0)
                final_bmp.SetPixelCnt(
                    dst_x, dst_y + py, tile_w, row_view, inc, color_mode, c4d.PIXELCNT_0
                )

            verify_pixel = final_bmp.GetPixel(dst_x, dst_y)
            print(f"[assemble_tiles]   final verify pixel ({dst_x},{dst_y}): {verify_pixel}")
            print(f"Assembled tile ({col}, {row}) from {tile_path}")

    # Save the assembled image
    final_path = f"{base}_{frame}{existing_ext}"
    output_dir = os.path.dirname(final_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Copy the color profile from the first tile to ensure consistency.
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

    final_filter = EXT_TO_FILTER.get(existing_ext.lower(), save_filter)
    print(f"[assemble_tiles] saving to: {final_path}")
    print(f"[assemble_tiles] save filter: {final_filter}, ext: {existing_ext}")
    final_bmp.Save(final_path, final_filter)
    print(f"Assembled {tiles_columns * tiles_rows} tiles into {final_path} ({full_w}x{full_h})")


def _assemble_multipass_tiles(
    mp_base: str,
    mp_ext: str,
    frame: int,
    tiles_columns: int,
    tiles_rows: int,
    save_filter: int,
) -> None:
    """Assemble multi-pass tile images into a single full-resolution multi-pass image.

    Multi-pass tiles are saved by C4D at full resolution (with only the tile region
    rendered). We extract each tile's region and composite them.

    Args:
        mp_base: The multi-pass output path stem (without extension).
        mp_ext: The file extension for multi-pass output.
        frame: The current frame number.
        tiles_columns: Number of tile columns.
        tiles_rows: Number of tile rows.
        save_filter: The C4D save filter ID (fallback).
    """
    padded_frame = str(frame).zfill(4)

    first_mp_path = f"{mp_base}_tile_0_0_{padded_frame}{mp_ext}"
    print(f"[assemble_tiles] looking for first multi-pass tile: {first_mp_path}")
    first_mp = c4d.bitmaps.BaseBitmap()
    mp_result = first_mp.InitWith(first_mp_path)
    if mp_result[0] != c4d.IMAGERESULT_OK:
        print(
            f"[assemble_tiles] WARNING: failed to load first multi-pass tile: {first_mp_path}, skipping multi-pass assembly"
        )
        return

    mp_full_w = first_mp.GetBw()
    mp_full_h = first_mp.GetBh()
    mp_tile_w = mp_full_w // tiles_columns
    mp_tile_h = mp_full_h // tiles_rows
    mp_bpp = first_mp.GetBt()

    mp_color_mode, mp_inc = determine_color_mode(mp_bpp)

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

    mp_profile = first_mp.GetColorProfile()
    if mp_profile is not None:
        mp_final.SetColorProfile(mp_profile)

    mp_final_filter = EXT_TO_FILTER.get(mp_ext.lower(), save_filter)
    mp_final.Save(mp_final_path, mp_final_filter)
    print(f"Assembled multi-pass {tiles_columns * tiles_rows} tiles into {mp_final_path}")


def assemble_tiles(
    doc: Any,
    data: dict,
    map_path: Any,
) -> None:
    """Assemble tile images into a single full-resolution image.

    Handles both beauty pass and multi-pass assembly.

    Args:
        doc: The active C4D document.
        data: The action data dict with tile grid info, frame, and output paths.
        map_path: Callable to remap file paths.
    """
    tiles_columns = int(data["total_tiles_column"])
    tiles_rows = int(data["total_tiles_row"])
    frame = int(data["frame"])
    output_path = data.get("output_path", "")
    multi_pass_path = data.get("multi_pass_path", "")

    if not output_path:
        raise RuntimeError("assemble_tiles: no output_path provided")

    output_path = map_path(output_path)
    if multi_pass_path:
        multi_pass_path = map_path(multi_pass_path)

    # Determine extension and save filter from the document's render format
    render_data = doc.GetActiveRenderData()
    format_id = render_data[c4d.RDATA_FORMAT] if render_data else 0
    ext, save_filter = get_format_info(format_id)

    base, existing_ext = os.path.splitext(output_path)
    if not existing_ext:
        existing_ext = ext

    _assemble_beauty_tiles(base, existing_ext, frame, tiles_columns, tiles_rows, save_filter)

    # Assemble multi-pass tiles if multi_pass_path is provided.
    if multi_pass_path:
        mp_base, mp_ext = os.path.splitext(multi_pass_path)
        if not mp_ext:
            mp_format_id = render_data[c4d.RDATA_MULTIPASS_SAVEFORMAT] if render_data else 0
            mp_ext = get_format_info(mp_format_id)[0]

        _assemble_multipass_tiles(
            mp_base, mp_ext, frame, tiles_columns, tiles_rows, save_filter
        )

    print("Finished Rendering")
