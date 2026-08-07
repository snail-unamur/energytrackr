"""EvolutionPlot module with commit-zoom selector and fixed y-axis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bokeh.models import ColumnDataSource
from bokeh.plotting import figure

from energytrackr.plot.builtin_plots.mixins import FontMixin, SingleCommitZoomMixin, draw_additional_objects
from energytrackr.plot.builtin_plots.registry import register_plot
from energytrackr.plot.core.context import Context
from energytrackr.plot.core.interfaces import BasePlot, Configurable


@dataclass(frozen=True)
class EvolutionPlotConfig:
    """Configuration for EvolutionPlot, including how wide the zoom box is."""

    template: str = "templates/base_plot.html"
    objects: list[str] = field(default_factory=list)
    zoom_window: int = 5  # number of commits on each side to show


@register_plot
class EvolutionPlot(SingleCommitZoomMixin, FontMixin, BasePlot, Configurable[EvolutionPlotConfig]):
    """Energy-per-commit evolution plot with commit zoom and fixed y-axis."""

    def __init__(self, **params: dict[str, Any]) -> None:
        """Initialize with optional `zoom_window` parameter.

        Args:
            **params: Arbitrary configuration parameters for EvolutionPlotConfig.
        """
        super().__init__(EvolutionPlotConfig, **params)

    def _make_sources(self, ctx: Context) -> dict[str, ColumnDataSource]:  # noqa: PLR6301
        x = ctx.stats["x_indices"]
        y = ctx.stats["medians"]
        return {"median": ColumnDataSource({"x": x, "y": y})}

    def _draw_glyphs(self, fig: figure, sources: dict[str, ColumnDataSource], ctx: Context) -> None:
        fig.line("x", "y", source=sources["median"], color="black", legend_label="Median")
        draw_additional_objects(self.config.objects, fig, ctx)

    def _configure(self, fig: figure, ctx: Context) -> None:
        """Apply fonts, axis labels, and freeze the y-axis to initial full-data range."""
        super()._configure(fig, ctx)

        # labels
        fig.xaxis[0].axis_label = "Commit (oldest → newest)"
        fig.yaxis[0].axis_label = f"Median {ctx.active_column} ({ctx.active_unit})"

    def _title(self, ctx: Context) -> str:  # noqa: PLR6301
        # Custom title including field
        return f"Energy Consumption - {ctx.active_column}"

    def _key(self, ctx: Context) -> str:  # noqa: ARG002, PLR6301
        # Store under 'Evolution'
        return "Evolution"
