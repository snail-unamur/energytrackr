"""ECDFComparison using BasePlot and mixins for cleaner composition."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from bokeh.models import ColumnDataSource, Range1d
from bokeh.palettes import Category10
from bokeh.plotting import figure

from energytrackr.plot.builtin_plots.mixins import (
    ComparisonBase,
    get_labels_and_dists,
    initial_commits,
)
from energytrackr.plot.builtin_plots.registry import register_plot
from energytrackr.plot.core.context import Context


@register_plot
class ECDFComparison(ComparisonBase):
    """Interactive ECDF comparison between two selected commits."""

    def __init__(self) -> None:
        """Initialize the ECDFComparison plot."""
        self._full_ecdf: ColumnDataSource | None = None
        self._labels: Sequence[str] | None = None
        self._init_indices: tuple[int, int] | None = None
        self._ds1: ColumnDataSource | None = None
        self._ds2: ColumnDataSource | None = None

    def _make_sources(self, ctx: Context) -> dict[str, Any]:
        # compute full ECDF data
        labels, dists = get_labels_and_dists(ctx)
        src_full, (_, _) = self._compute_ecdf(dists)
        # initial indices (oldest vs newest)
        i1, i2 = initial_commits(labels)

        # prepare per-commit ecdf data for JS and callbacks
        self._full_ecdf = src_full
        self._labels = labels
        # store initial indices for plot drawing
        self._init_indices = (int(i1), int(i2))
        return {"full_ecdf": src_full, "labels": labels}

    def _make_figure(self, ctx: Context) -> figure:
        # derive x-range from distributions
        dists = ctx.artefacts["distributions"]
        all_vals = np.concatenate([np.asarray(arr, float) for arr in dists])
        x_min, x_max = float(all_vals.min()), float(all_vals.max())
        return figure(
            title=self._title(ctx),
            x_range=Range1d(start=x_min, end=x_max),
            sizing_mode="stretch_width",
            tools="pan,box_zoom,reset,save,wheel_zoom,hover",
            toolbar_location="above",
            x_axis_label=f"{ctx.active_column} ({ctx.active_unit})",
            y_axis_label="ECDF",
        )

    def _draw_glyphs(self, fig: figure, sources: dict[str, ColumnDataSource], ctx: Context) -> None:  # noqa: ARG002
        # unpack
        src_full = self._full_ecdf
        assert self._init_indices is not None
        i1, i2 = self._init_indices
        # build step data sources
        assert src_full is not None
        raw1 = self._make_ecdf_ds(src_full, i1)
        raw2 = self._make_ecdf_ds(src_full, i2)
        ds1 = ColumnDataSource(pd.DataFrame({"x": raw1["x"], "y": raw1["y"]}))
        ds2 = ColumnDataSource(pd.DataFrame({"x": raw2["x"], "y": raw2["y"]}))
        self._ds1 = ds1
        self._ds2 = ds2
        # render ECDF steps
        palette = Category10[3]
        fig.step("x", "y", source=ds1, mode="after", line_width=2, line_color=palette[0], legend_label="Commit A")
        fig.step("x", "y", source=ds2, mode="after", line_width=2, line_color=palette[1], legend_label="Commit B")

    def _configure(self, fig: figure, ctx: Context) -> None:
        super()._configure(fig, ctx)
        # legend placement
        if fig.legend:
            for legend in fig.legend:
                legend.location = "bottom_right"

    def _callback_js_path(self) -> Path:  # noqa: PLR6301
        return Path(__file__).parent / "static" / "ecdf_comparison.js"

    def _callback_args(self, fig: figure, ctx: Context) -> dict[str, Any]:  # noqa: ARG002
        return {
            "full_ecdf": self._full_ecdf,
            "src1": self._ds1,
            "src2": self._ds2,
            "plot": fig,
            "labels": self._labels,
        }

    def _hover_tooltips(self, ctx: Context) -> list[tuple[str, str]]:  # noqa: ARG002, PLR6301
        return [
            ("Value", "@x{0.00} J"),
            ("ECDF", "@y{0.00}"),
        ]

    def _title(self, ctx: Context) -> str:  # noqa: PLR6301
        return f"Empirical CDF: {ctx.active_column}"

    def _key(self, ctx: Context) -> str:  # noqa: ARG002, PLR6301
        return "ECDF Comparison"

    @staticmethod
    def _compute_ecdf(dists: list[np.ndarray]) -> tuple[ColumnDataSource, tuple[float, float]]:
        xs_list: list[list[float]] = []
        ys_list: list[list[float]] = []
        for arr in dists:
            data = np.sort(np.asarray(arr, float))
            xs_list.append(data.tolist())
            ys_list.append((np.arange(1, len(data) + 1) / len(data)).tolist())
        all_vals = np.concatenate([np.asarray(arr, float) for arr in dists])
        vmin, vmax = float(all_vals.min()), float(all_vals.max())
        return ColumnDataSource({"ecdf_x": xs_list, "ecdf_y": ys_list}), (vmin, vmax)

    @staticmethod
    def _make_ecdf_ds(full_src: ColumnDataSource, idx: int) -> dict[str, list[float]]:
        return {
            "x": full_src.data["ecdf_x"][idx],
            "y": full_src.data["ecdf_y"][idx],
        }
