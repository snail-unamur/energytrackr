"""QQComparison using BasePlot and mixins for cleaner composition."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from bokeh.models import ColumnDataSource, LinearColorMapper
from bokeh.palettes import Viridis256
from bokeh.plotting import figure

from energytrackr.plot.builtin_plots.mixins import (
    ColorbarMixin,
    CommitSelectorsMixin,
    FontMixin,
    HoverMixin,
    get_labels_and_dists,
    initial_commits,
)
from energytrackr.plot.builtin_plots.registry import register_plot
from energytrackr.plot.core.context import Context
from energytrackr.plot.core.interfaces import BasePlot


@register_plot
class QQComparison(
    CommitSelectorsMixin,
    FontMixin,
    ColorbarMixin,
    HoverMixin,
    BasePlot,
):
    """Interactive QQ-plot comparing two commits with percentile coloring and tooltips."""

    def __init__(self) -> None:
        """Initialize the QQComparison plot."""
        super().__init__()
        self._current_sources: dict[str, Any] = {}

    def _make_sources(self, ctx: Context) -> dict[str, Any]:
        labels, dists = get_labels_and_dists(ctx)
        full_quant = self._compute_quantiles(dists)
        first, second = initial_commits(labels)
        i1, i2 = labels.index(first), labels.index(second)

        # Build data sources
        qq_data = self._make_qq_ds(full_quant, i1, i2)
        qq_src = ColumnDataSource(pd.DataFrame(qq_data))
        idl_data = self._make_identity_ds(qq_src)
        idl_src = ColumnDataSource(pd.DataFrame(idl_data))

        # Store for callback wiring
        self._current_sources = {
            "full_quant": full_quant,
            "commits": labels,
            "labels": labels,
            "qq_src": qq_src,
            "idl_src": idl_src,
        }
        return self._current_sources

    def _draw_glyphs(self, fig: figure, sources: dict[str, Any], ctx: Context) -> None:  # noqa: ARG002, PLR6301
        # Set axis labels
        for xaxis in fig.xaxis:
            xaxis.axis_label = "Commit A Energy (J)"
        for yaxis in fig.yaxis:
            yaxis.axis_label = "Commit B Energy (J)"

        mapper = LinearColorMapper(palette=Viridis256, low=0, high=100)
        # QQ scatter
        fig.circle(
            "x",
            "y",
            source=sources["qq_src"],
            radius=0.04,
            fill_color={"field": "percent", "transform": mapper},
            line_color=None,
        )
        # Identity line
        fig.line(
            "x",
            "y",
            source=sources["idl_src"],
            line_dash="dashed",
            line_color="black",
            line_width=2,
        )

    def _title(self, ctx: Context) -> str:  # noqa: PLR6301
        return f"QQ-Plot: {ctx.active_column}"

    def _key(self, ctx: Context) -> str:  # noqa: ARG002, PLR6301
        return "Quantile Quantile"

    def _callback_js_path(self) -> Path:  # noqa: PLR6301
        return Path(__file__).parent / "static" / "qq_comparison.js"

    def _callback_args(self, fig: figure, ctx: Context) -> dict[str, Any]:  # noqa: ARG002
        args = dict(self._current_sources)
        args["plot"] = fig
        return args

    def _hover_tooltips(self, ctx: Context) -> list[tuple[str, str]]:  # noqa: ARG002, PLR6301
        return [
            ("Pct", "@percent%"),
            ("A", "@x{0.00} J"),
            ("B", "@y{0.00} J"),
        ]

    @staticmethod
    def _compute_quantiles(dists: list[np.ndarray]) -> dict[str, Any]:
        perc = np.linspace(0, 100, 101)
        table = [np.percentile(np.asarray(arr), perc).tolist() for arr in dists]
        return {"quant": table, "percent": perc}

    @staticmethod
    def _make_qq_ds(full_quant: dict[str, Any], i: int, j: int) -> dict[str, Any]:
        quants = full_quant["quant"]
        perc = np.asarray(full_quant["percent"], dtype=np.float64)
        return {
            "x": np.asarray(quants[i], dtype=np.float64),
            "y": np.asarray(quants[j], dtype=np.float64),
            "percent": perc,
        }

    @staticmethod
    def _make_identity_ds(qq_src: ColumnDataSource) -> dict[str, Any]:
        xs = np.asarray(qq_src.data["x"]).flatten()
        ys = np.asarray(qq_src.data["y"]).flatten()
        vmin = float(np.min(np.concatenate([xs, ys])))
        vmax = float(np.max(np.concatenate([xs, ys])))
        return {"x": [vmin, vmax], "y": [vmin, vmax]}
