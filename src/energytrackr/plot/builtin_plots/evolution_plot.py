"""EvolutionPlot module with commit-zoom selector and fixed y-axis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bokeh.models import ColumnDataSource, LinearAxis, Range1d
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
    secondary_column: str | None = None   # CSV column to overlay on right Y-axis (e.g. "seconds")
    secondary_unit: str = "s"             # Unit for the right Y-axis label
    secondary_label: str = "Runtime"      # Human label for the secondary axis / legend
    secondary_visible: bool = False        # Whether the secondary line is visible by default


@register_plot
class EvolutionPlot(SingleCommitZoomMixin, FontMixin, BasePlot, Configurable[EvolutionPlotConfig]):
    """Energy-per-commit evolution plot with commit zoom, fixed y-axis, and optional secondary overlay."""

    def __init__(self, **params: dict[str, Any]) -> None:
        """Initialize with optional `zoom_window` and secondary overlay parameters.

        Args:
            **params: Arbitrary configuration parameters for EvolutionPlotConfig.
        """
        super().__init__(EvolutionPlotConfig, **params)

    def _has_secondary(self, ctx: Context) -> bool:
        """Return True when secondary data is both configured and available in ctx."""
        return bool(self.config.secondary_column and "secondary_medians" in ctx.stats)

    def _make_figure(self, ctx: Context) -> figure:
        """Create figure, adding a secondary right Y-axis when secondary data is available."""
        fig = figure(
            title=self._title(ctx),
            sizing_mode="stretch_width",
            tools="pan,box_zoom,reset,save,wheel_zoom",
            toolbar_location="above",
        )
        if self._has_secondary(ctx):
            sec = ctx.stats["secondary_medians"]
            margin = (max(sec) - min(sec)) * 0.1 or 0.5
            fig.extra_y_ranges = {
                "secondary": Range1d(start=min(sec) - margin, end=max(sec) + margin),
            }
            fig.add_layout(
                LinearAxis(
                    y_range_name="secondary",
                    axis_label=f"Median {self.config.secondary_label} ({self.config.secondary_unit})",
                ),
                "right",
            )
        return fig

    def _make_sources(self, ctx: Context) -> dict[str, ColumnDataSource]:
        data: dict[str, Any] = {
            "x": ctx.stats["x_indices"],
            "y": ctx.stats["medians"],
        }
        if self._has_secondary(ctx):
            data["y_secondary"] = ctx.stats["secondary_medians"]
        return {"main": ColumnDataSource(data)}

    def _draw_glyphs(self, fig: figure, sources: dict[str, ColumnDataSource], ctx: Context) -> None:
        fig.line("x", "y", source=sources["main"], color="black", legend_label="Median")
        if self._has_secondary(ctx):
            fig.line(
                "x", "y_secondary",
                source=sources["main"],
                color="crimson",
                line_dash="dashed",
                line_width=1.5,
                y_range_name="secondary",
                legend_label=f"Median {self.config.secondary_label} ({self.config.secondary_unit})",
                visible=self.config.secondary_visible,
            )
        draw_additional_objects(self.config.objects, fig, ctx)

    def _configure(self, fig: figure, ctx: Context) -> None:
        """Apply fonts, axis labels, and freeze the y-axis to initial full-data range."""
        super()._configure(fig, ctx)

        # labels
        fig.xaxis[0].axis_label = "Commit (oldest \u2192 newest)"
        fig.yaxis[0].axis_label = f"Median {ctx.active_column} ({ctx.active_unit})"

        # Enable legend click-to-hide when secondary is present
        if self._has_secondary(ctx):
            fig.legend.click_policy = "hide"

    def _title(self, ctx: Context) -> str:  # noqa: PLR6301
        return f"Energy Consumption - {ctx.active_column}"

    def _key(self, ctx: Context) -> str:  # noqa: ARG002, PLR6301
        return "Evolution"
