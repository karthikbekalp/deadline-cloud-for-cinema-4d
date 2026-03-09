# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
from __future__ import annotations

from deadline.cinema4d_submitter.tile_utils import build_tile_task_parameters


class TestBuildTileTaskParameters:
    def test_returns_correct_parameter_definitions(self):
        params, _ = build_tile_task_parameters(3, 2)
        assert params == [
            {"name": "TileCol", "type": "INT", "range": "0-2"},
            {"name": "TileRow", "type": "INT", "range": "0-1"},
        ]

    def test_returns_combination_expression(self):
        _, expression = build_tile_task_parameters(3, 2)
        assert expression == "Frame * TileCol * TileRow"

    def test_single_tile(self):
        params, _ = build_tile_task_parameters(1, 1)
        assert params[0]["range"] == "0-0"
        assert params[1]["range"] == "0-0"
