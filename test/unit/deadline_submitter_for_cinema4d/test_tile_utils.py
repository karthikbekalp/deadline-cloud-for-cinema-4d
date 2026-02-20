# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
from __future__ import annotations

import pytest

from deadline.cinema4d_submitter.tile_utils import TileRegion, compute_tile_regions


class TestComputeTileRegions:
    def test_single_tile(self):
        regions = compute_tile_regions(1, 1)
        assert len(regions) == 1
        r = regions[0]
        assert r.column == 0 and r.row == 0

    def test_2x2_grid(self):
        regions = compute_tile_regions(2, 2)
        assert len(regions) == 4
        # Row-major order: (0,0), (1,0), (0,1), (1,1)
        assert regions[0] == TileRegion(0, 0)
        assert regions[1] == TileRegion(1, 0)
        assert regions[2] == TileRegion(0, 1)
        assert regions[3] == TileRegion(1, 1)

    def test_3x1_grid(self):
        regions = compute_tile_regions(3, 1)
        assert len(regions) == 3
        assert regions[0].column == 0
        assert regions[1].column == 1
        assert regions[2].column == 2
        assert all(r.row == 0 for r in regions)

    def test_invalid_tiles_x(self):
        with pytest.raises(ValueError):
            compute_tile_regions(0, 2)

    def test_invalid_tiles_y(self):
        with pytest.raises(ValueError):
            compute_tile_regions(2, -1)

    def test_count_matches_dimensions(self):
        regions = compute_tile_regions(4, 3)
        assert len(regions) == 12


class TestInjectTileIdentifier:
    def test_with_extension(self):
        from deadline.cinema4d_submitter.tile_utils import inject_tile_identifier

        result = inject_tile_identifier("/output/render.exr", 1, 2)
        assert result == "/output/render_tile_1_2.exr"

    def test_without_extension(self):
        from deadline.cinema4d_submitter.tile_utils import inject_tile_identifier

        result = inject_tile_identifier("/output/render", 0, 0)
        assert result == "/output/render_tile_0_0"

    def test_multi_dot_extension(self):
        from deadline.cinema4d_submitter.tile_utils import inject_tile_identifier

        result = inject_tile_identifier("/output/my.scene.png", 3, 1)
        assert result == "/output/my.scene_tile_3_1.png"
