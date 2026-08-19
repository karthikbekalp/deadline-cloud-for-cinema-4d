# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Shared Redshift OCIO studio scene for Cinema 4D integration tests."""

from __future__ import annotations

import math
import os
from typing import Any

import c4d
import maxon

WIDTH = 384
HEIGHT = 216
ACES_DEFAULT_VIEW_TRANSFORM = 0
ACES_UNTONE_MAPPED_VIEW_TRANSFORM = 3
REDSHIFT_RENDERER_ID = 1036219

_REDSHIFT_NODE_SPACE = maxon.Id("com.redshift3d.redshift4c4d.class.nodespace")
_STANDARD_MATERIAL_PORT = "com.redshift3d.redshift4c4d.nodes.core.standardmaterial"


def _redshift_material(
    doc: Any,
    name: str,
    color: tuple[float, float, float],
    *,
    roughness: float = 0.35,
    metalness: float = 0.0,
    emission: tuple[float, float, float] | None = None,
) -> Any:
    material = c4d.BaseMaterial(c4d.Mmaterial)
    material.SetName(name)
    doc.InsertMaterial(material)
    node_material = material.GetNodeMaterialReference()
    node_material.CreateDefaultGraph(_REDSHIFT_NODE_SPACE)
    graph = node_material.GetGraph(_REDSHIFT_NODE_SPACE)

    standard_node = None
    base_color_port = f"{_STANDARD_MATERIAL_PORT}.base_color"
    root = graph.GetViewRoot()
    nodes = root.GetChildren()
    for node in nodes:
        if node.GetId().ToString().split("@", 1)[0] == "standardmaterial":
            standard_node = node
            break
    if standard_node is None:
        raise RuntimeError("Redshift Standard Material node was not created")

    with graph.BeginTransaction() as transaction:
        inputs = standard_node.GetInputs()
        inputs.FindChild(base_color_port).SetPortValue(maxon.Color(*color))
        inputs.FindChild(f"{_STANDARD_MATERIAL_PORT}.refl_roughness").SetPortValue(roughness)
        inputs.FindChild(f"{_STANDARD_MATERIAL_PORT}.metalness").SetPortValue(metalness)
        if emission is not None:
            inputs.FindChild(f"{_STANDARD_MATERIAL_PORT}.base_color_weight").SetPortValue(0.0)
            inputs.FindChild(f"{_STANDARD_MATERIAL_PORT}.emission_color").SetPortValue(
                maxon.Color(*emission)
            )
            inputs.FindChild(f"{_STANDARD_MATERIAL_PORT}.emission_weight").SetPortValue(1.0)
        transaction.Commit()

    return material


def _attach_material(obj: Any, material: Any) -> None:
    tag = c4d.TextureTag()
    tag.SetMaterial(material)
    obj.InsertTag(tag)


def _add_cube(
    doc: Any,
    name: str,
    size: tuple[float, float, float],
    position: tuple[float, float, float],
    material: Any,
    *,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    fillet: float = 0.0,
) -> Any:
    cube = c4d.BaseObject(c4d.Ocube)
    cube.SetName(name)
    cube[c4d.PRIM_CUBE_LEN] = c4d.Vector(*size)
    if fillet > 0.0:
        cube[c4d.PRIM_CUBE_DOFILLET] = True
        cube[c4d.PRIM_CUBE_FRAD] = fillet
        cube[c4d.PRIM_CUBE_SUBF] = 4
    cube.SetAbsPos(c4d.Vector(*position))
    cube.SetAbsRot(c4d.Vector(*(math.radians(value) for value in rotation)))
    _attach_material(cube, material)
    doc.InsertObject(cube)
    return cube


def _point_at(obj: Any, target: tuple[float, float, float]) -> None:
    direction = c4d.Vector(*target) - obj.GetAbsPos()
    obj.SetAbsRot(c4d.utils.VectorToHPB(direction))


def _add_area_light(
    doc: Any,
    name: str,
    position: tuple[float, float, float],
    target: tuple[float, float, float],
    color: tuple[float, float, float],
    exposure: float,
    size: tuple[float, float],
) -> None:
    light = c4d.BaseObject(c4d.Orslight)
    light.SetName(name)
    light[c4d.REDSHIFT_LIGHT_TYPE] = c4d.REDSHIFT_LIGHT_TYPE_PHYSICAL_AREA
    light[c4d.REDSHIFT_LIGHT_PHYSICAL_COLORMODE] = c4d.REDSHIFT_LIGHT_COLORMODE_COLOR
    light[c4d.REDSHIFT_LIGHT_PHYSICAL_COLOR] = c4d.Vector(*color)
    light[c4d.REDSHIFT_LIGHT_PHYSICAL_INTENSITY] = 1.0
    light[c4d.REDSHIFT_LIGHT_PHYSICAL_EXPOSURE] = exposure
    light[c4d.REDSHIFT_LIGHT_PHYSICAL_AREA_GEOMETRY] = c4d.REDSHIFT_LIGHT_AREA_GEOMETRY_RECTANGLE
    light[c4d.REDSHIFT_LIGHT_PHYSICAL_AREA_SIZEX] = size[0]
    light[c4d.REDSHIFT_LIGHT_PHYSICAL_AREA_SIZEY] = size[1]
    light[c4d.REDSHIFT_LIGHT_PHYSICAL_AREA_VISIBLE_IN_RENDER] = False
    light.SetAbsPos(c4d.Vector(*position))
    _point_at(light, target)
    doc.InsertObject(light)


def _build_geometry(doc: Any) -> None:
    backdrop = _redshift_material(
        doc,
        "Charcoal backdrop",
        (0.028, 0.035, 0.05),
        roughness=0.62,
    )
    floor = _redshift_material(
        doc,
        "Neutral floor",
        (0.12, 0.13, 0.15),
        roughness=0.28,
        metalness=0.15,
    )
    orange = _redshift_material(
        doc,
        "Burnished orange",
        (0.95, 0.09, 0.015),
        roughness=0.2,
        metalness=0.25,
    )
    cyan = _redshift_material(
        doc,
        "Glossy cyan",
        (0.015, 0.42, 0.72),
        roughness=0.14,
        metalness=0.05,
    )
    magenta = _redshift_material(
        doc,
        "Matte magenta",
        (0.72, 0.025, 0.2),
        roughness=0.48,
    )
    green = _redshift_material(
        doc,
        "Metallic green",
        (0.025, 0.52, 0.13),
        roughness=0.24,
        metalness=0.7,
    )
    blue_emission = _redshift_material(
        doc,
        "HDR blue strip",
        (0.0, 0.0, 0.0),
        emission=(0.02, 0.65, 6.0),
    )

    _add_cube(
        doc,
        "Backdrop",
        (1300, 760, 30),
        (0, 90, 430),
        backdrop,
    )
    _add_cube(
        doc,
        "Floor",
        (1300, 30, 1050),
        (0, -210, 50),
        floor,
        fillet=8,
    )
    _add_cube(
        doc,
        "Diagonal HDR strip",
        (980, 24, 18),
        (0, 115, 395),
        blue_emission,
        rotation=(0, 0, -8),
        fillet=6,
    )

    sphere = c4d.BaseObject(c4d.Osphere)
    sphere.SetName("Orange sphere")
    sphere[c4d.PRIM_SPHERE_RAD] = 150
    sphere[c4d.PRIM_SPHERE_SUB] = 48
    sphere.SetAbsPos(c4d.Vector(-285, -55, 45))
    _attach_material(sphere, orange)
    doc.InsertObject(sphere)

    _add_cube(
        doc,
        "Cyan beveled cube",
        (225, 225, 225),
        (-35, -50, 60),
        cyan,
        rotation=(12, -24, 8),
        fillet=24,
    )

    torus = c4d.BaseObject(c4d.Otorus)
    torus.SetName("Green torus")
    torus[c4d.PRIM_TORUS_OUTERRAD] = 150
    torus[c4d.PRIM_TORUS_INNERRAD] = 48
    torus[c4d.PRIM_TORUS_SEG] = 64
    torus[c4d.PRIM_TORUS_CSUB] = 24
    torus.SetAbsPos(c4d.Vector(285, -45, 75))
    torus.SetAbsRot(c4d.Vector(math.radians(78), math.radians(-10), math.radians(16)))
    _attach_material(torus, green)
    doc.InsertObject(torus)

    pyramid = c4d.BaseObject(c4d.Opyramid)
    pyramid.SetName("Magenta pyramid")
    pyramid[c4d.PRIM_PYRAMID_LEN] = c4d.Vector(230, 285, 230)
    pyramid.SetAbsPos(c4d.Vector(115, 85, 205))
    pyramid.SetAbsRot(c4d.Vector(0, math.radians(24), math.radians(-5)))
    _attach_material(pyramid, magenta)
    doc.InsertObject(pyramid)

    exposure_values = (0.18, 1.0, 4.0, 16.0)
    exposure_positions = (-300, -100, 100, 300)
    for value, x_position in zip(exposure_values, exposure_positions):
        swatch_material = _redshift_material(
            doc,
            f"Exposure {value:g}",
            (0.0, 0.0, 0.0),
            emission=(value, value, value),
        )
        _add_cube(
            doc,
            f"Exposure swatch {value:g}",
            (118, 42, 18),
            (x_position, 285, 395),
            swatch_material,
            fillet=5,
        )

    target = (0, 10, 80)
    _add_area_light(
        doc,
        "Warm key",
        (-430, 430, -360),
        target,
        (1.0, 0.68, 0.48),
        6.0,
        (430, 430),
    )
    _add_area_light(
        doc,
        "Cool fill",
        (470, 160, -220),
        target,
        (0.3, 0.62, 1.0),
        4.5,
        (340, 340),
    )
    _add_area_light(
        doc,
        "Magenta rim",
        (60, 440, 360),
        target,
        (1.0, 0.18, 0.45),
        4.0,
        (280, 280),
    )

    camera = c4d.BaseObject(c4d.Ocamera)
    camera.SetName("OCIO studio camera")
    camera.SetAbsPos(c4d.Vector(0, 70, -1320))
    _point_at(camera, (0, 35, 90))
    camera[c4d.CAMERA_FOCUS] = 52.0
    doc.InsertObject(camera)
    doc.GetRenderBaseDraw().SetSceneCamera(camera)


def build_ocio_scene(
    output_dir: str,
    scene_name: str,
    view_transform: int,
) -> None:
    """Build and save the shared Redshift OCIO scene."""
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    doc = c4d.documents.GetActiveDocument()
    doc.Flush()
    _build_geometry(doc)

    doc[c4d.DOCUMENT_COLOR_MANAGEMENT] = c4d.DOCUMENT_COLOR_MANAGEMENT_OCIO
    doc[c4d.DOCUMENT_OCIO_PRESET] = c4d.DOCUMENT_OCIO_PRESET_ACES
    doc[c4d.DOCUMENT_OCIO_VIEW_TRANSFORM] = view_transform

    render_data = doc.GetActiveRenderData()
    render_data[c4d.RDATA_RENDERENGINE] = REDSHIFT_RENDERER_ID
    render_data[c4d.RDATA_XRES] = WIDTH
    render_data[c4d.RDATA_YRES] = HEIGHT
    render_data[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(1, doc.GetFps())
    render_data[c4d.RDATA_FRAMETO] = c4d.BaseTime(1, doc.GetFps())
    render_data[c4d.RDATA_FORMAT] = c4d.FILTER_PNG
    render_data[c4d.RDATA_FORMATDEPTH] = c4d.RDATA_FORMATDEPTH_8
    render_data[c4d.RDATA_ALPHACHANNEL] = False
    render_data[c4d.RDATA_MULTIPASS_SAVEIMAGE] = False
    if hasattr(c4d, "RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER"):
        render_data.GetDataInstance()[c4d.RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER] = True

    render_data[c4d.RDATA_PATH] = "renders/$prj"

    scene_path = os.path.join(output_dir, scene_name)
    doc.SetDocumentPath(output_dir)
    doc.SetDocumentName(scene_name)
    if not c4d.documents.SaveDocument(
        doc,
        scene_path,
        c4d.SAVEDOCUMENTFLAGS_0,
        c4d.FORMAT_C4DEXPORT,
    ):
        raise RuntimeError(f"Failed to save integration scene: {scene_path}")
    c4d.EventAdd()
