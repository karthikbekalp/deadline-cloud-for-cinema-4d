# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TileRegion:
    """A rectangular sub-region of a frame defined by normalized coordinates (0.0–1.0)."""

    column: int
    row: int
    left: float
    top: float
    right: float
    bottom: float


def compute_tile_regions(tiles_x: int, tiles_y: int) -> list[TileRegion]:
    """
    Compute tile regions for a grid of tiles_x columns and tiles_y rows.

    Each boundary is a normalized float in [0.0, 1.0].
    Returns tiles_x * tiles_y TileRegion objects, ordered row-major
    (row 0 col 0, row 0 col 1, ..., row 1 col 0, ...).

    Raises:
        ValueError: If tiles_x or tiles_y is less than 1.
    """
    if tiles_x < 1 or tiles_y < 1:
        raise ValueError(
            f"Tile grid dimensions must be >= 1, got tiles_x={tiles_x}, tiles_y={tiles_y}"
        )

    regions: list[TileRegion] = []
    for row in range(tiles_y):
        for col in range(tiles_x):
            regions.append(
                TileRegion(
                    column=col,
                    row=row,
                    left=col / tiles_x,
                    top=row / tiles_y,
                    right=(col + 1) / tiles_x,
                    bottom=(row + 1) / tiles_y,
                )
            )
    return regions


def inject_tile_identifier(path: str, column: int, row: int) -> str:
    """
    Insert a tile identifier suffix before the file extension in the given path.

    The tile identifier format is ``_tile_{column}_{row}``.
    If the path has no file extension, the identifier is appended to the end.

    Args:
        path: The original file path.
        column: Zero-based column index in the tile grid.
        row: Zero-based row index in the tile grid.

    Returns:
        The modified path with the tile identifier inserted.
    """
    suffix = f"_tile_{column}_{row}"
    dot_index = path.rfind(".")
    if dot_index == -1:
        return path + suffix
    return path[:dot_index] + suffix + path[dot_index:]
