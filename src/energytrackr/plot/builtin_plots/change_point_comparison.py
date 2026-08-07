"""ChangePointComparison using BasePlot and mixins for cleaner composition."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import ruptures as rpt
from bokeh.models import ColumnDataSource, HoverTool
from bokeh.plotting import figure

from energytrackr.plot.builtin_plots.mixins import FontMixin, HoverMixin, draw_additional_objects
from energytrackr.plot.builtin_plots.registry import register_plot
from energytrackr.plot.core.context import Context
from energytrackr.plot.core.interfaces import BasePlot, Configurable


@dataclass(frozen=True)
class ChangePointComparisonConfig:
    """Configuration for the ChangePointComparison plot."""

    objects: list[str] = field(default_factory=list)


@register_plot
class ChangePointComparison(FontMixin, HoverMixin, BasePlot, Configurable[ChangePointComparisonConfig]):
    """Renders a median-trend plot with change-point detection overlays."""

    def __init__(self, **params: dict[str, Any]) -> None:
        """Initialize the ChangePointComparison plot."""
        super().__init__(ChangePointComparisonConfig, **params)

    def _make_sources(self, ctx: Context) -> dict[str, Any]:  # noqa: PLR6301
        labels: list[str] = ctx.stats["short_hashes"]
        dists: list[list[float]] = ctx.artefacts["distributions"]
        medians = np.array([float(np.median(arr)) for arr in dists])
        idx = np.arange(len(labels))
        # detect change-points using PELT + RBF
        algo = rpt.Pelt(model="rbf").fit(medians)
        breakpoints = algo.predict(pen=3)
        cps = [bp for bp in breakpoints if bp < len(medians)]

        source = ColumnDataSource(
            data={
                "commit": labels,
                "med": medians.tolist(),
                "idx": idx,
            },
        )

        return {"source": source, "cps": cps, "medians": medians}

    def _draw_glyphs(self, fig: figure, sources: dict[str, Any], ctx: Context) -> None:
        # median trend line
        median_line = fig.line(
            x="idx",
            y="med",
            source=sources["source"],
            line_width=2,
            name="median_line",
            legend_label="Median",
        )
        # change-point segments
        if cps := sources["cps"]:
            medians = sources["medians"]
            segment_source = ColumnDataSource({
                "x": [sources["source"].data["idx"][i] for i in cps],
                "y0": [medians.min()] * len(cps),
                "y1": [medians.max()] * len(cps),
            })
            fig.segment(
                x0="x",
                y0="y0",
                x1="x",
                y1="y1",
                source=segment_source,
                line_dash="dashed",
                line_color="firebrick",
                line_width=2,
                legend_label="Change Points",
            )
        # add hover on median line
        hover = HoverTool(
            tooltips=[("Commit", "@commit"), ("Median", "@med{0.00} J")],
            mode="vline",
            renderers=[median_line],
        )
        fig.add_tools(hover)

        draw_additional_objects(self.config.objects, fig, ctx)

    def _configure(self, fig: figure, ctx: Context) -> None:
        super()._configure(fig, ctx)
        # axis labels
        fig.xaxis[0].axis_label = "Commit (oldest → newest)"
        fig.yaxis[0].axis_label = f"Median {ctx.active_column} ({ctx.active_unit})"

    def _title(self, ctx: Context) -> str:  # noqa: PLR6301
        return f"Change-Point Detection: {ctx.active_column} Medians"

    def _key(self, ctx: Context) -> str:  # noqa: ARG002, PLR6301
        return "Change Point Detection"

    def _hover_tooltips(self, ctx: Context) -> list[tuple[str, str]]:  # noqa: ARG002, PLR6301
        return []
