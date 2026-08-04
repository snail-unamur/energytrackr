"""ViolinComparison using BasePlot and mixins for cleaner composition."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from bokeh.models import ColumnDataSource, Label, Span
from bokeh.models.tickers import FixedTicker
from bokeh.plotting import figure
from scipy.stats import gaussian_kde

from energytrackr.plot.builtin_plots.mixins import (
    ComparisonBase,
    get_labels_and_dists,
)
from energytrackr.plot.builtin_plots.registry import register_plot
from energytrackr.plot.core.context import Context
from energytrackr.utils.exceptions import PlotLabelsNotSetError, PlotSourcesNotSetError


@register_plot
class ViolinComparison(
    ComparisonBase,
):
    """Interactive violin plot comparing two selected commits with hover tooltips."""

    def __init__(self) -> None:
        """Initialize the ViolinComparison plot."""
        self._kde_src: ColumnDataSource | None = None
        self._medians: list[float] | None = None
        self._labels: list[str] | None = None
        self._width: float | None = None
        self._sources: dict[str, Any] | None = None

    def _make_sources(self, ctx: Context) -> dict[str, Any]:
        labels, dists = get_labels_and_dists(ctx)
        kde_src, medians = self._compute_kdes(dists)
        # store for callback wiring and drawing
        self._kde_src = kde_src
        self._medians = medians
        self._labels = labels
        self._width = 0.4
        return {"kde_src": kde_src}

    def _make_figure(self, ctx: Context) -> figure:
        field = ctx.energy_fields[0]
        p = figure(
            title=self._title(ctx),
            sizing_mode="stretch_width",
            tools="pan,box_zoom,reset,save,wheel_zoom",
            toolbar_location="above",
            y_axis_label=f"{field} (J)",
        )
        return p

    def _draw_glyphs(self, fig: figure, sources: dict[str, ColumnDataSource], ctx: Context) -> None:  # noqa: ARG002
        labels = self._labels
        medians = self._medians
        kde_src = self._kde_src
        w = self._width
        if kde_src is None or medians is None or labels is None or w is None:
            raise ValueError()

        i1, i2 = 0, -1
        # initial patch data
        ds1 = ColumnDataSource(self._make_patch_ds(kde_src, i1, 0, labels[i1], w))
        ds2 = ColumnDataSource(self._make_patch_ds(kde_src, i2, 1, labels[i2], w))
        # render violins
        self._render_violin(fig, ds1, fill_color="lightsteelblue", legend_label=f"{labels[i2]} density")
        self._render_violin(
            fig,
            ds2,
            fill_color="lightcoral" if medians[i2] > medians[i1] else "lightgreen",
            legend_label=f"{labels[i1]} density",
        )
        # median spans and difference label
        span1, span2 = self._add_median_spans(fig, medians, i1, i2)
        diff_label = self._add_diff_label(fig, medians, i1, i2, kde_src)

        # store for JS callbacks
        self._sources = {
            "kde_src": kde_src,
            "violin1_ds": ds1,
            "violin2_ds": ds2,
            "span1": span1,
            "span2": span2,
            "label_diff": diff_label,
            "width": w,
            "labels": labels,
        }

    def _callback_js_path(self) -> Path:  # noqa: PLR6301
        return Path(__file__).parent / "static" / "violin_comparison.js"

    def _callback_args(self, fig: figure, ctx: Context) -> dict[str, Any]:
        if self._sources is None:
            raise PlotSourcesNotSetError(self._key(ctx))
        self._sources.update({"plot": fig, "ticker": fig.xaxis[0].ticker})
        return self._sources

    def _configure(self, fig: figure, ctx: Context) -> None:
        super()._configure(fig, ctx)
        # configure fixed x-axis ticks
        if self._labels is None:
            raise PlotLabelsNotSetError(self._key(ctx))
        self._configure_xaxis(fig, self._labels[0], self._labels[-1])

    def _hover_tooltips(self, ctx: Context) -> list[tuple[str, str]]:  # noqa: PLR6301
        field = ctx.energy_fields[0]
        return [
            ("Commit", "@commit"),
            (field, "@y{0.00} J"),
        ]

    def _title(self, ctx: Context) -> str:  # noqa: PLR6301
        return f"Violin Plot: {ctx.energy_fields[0]}"

    def _key(self, ctx: Context) -> str:  # noqa: ARG002, PLR6301
        return "Violin"

    @staticmethod
    def _compute_kdes(dists: list[np.ndarray]) -> tuple[ColumnDataSource, list[float]]:
        kde_x_list: list[list[float]] = []
        kde_y_list: list[list[float]] = []
        medians: list[float] = []

        for arr in dists:
            a = np.asarray(arr, float)
            grid = np.linspace(a.min(), a.max(), 200)
            dens = gaussian_kde(a)(grid)
            kde_x_list.append((dens / dens.max()).tolist())
            kde_y_list.append(grid.tolist())
            medians.append(float(np.median(a)))
        src = ColumnDataSource({"kde_x": kde_x_list, "kde_y": kde_y_list, "median": medians})
        return src, medians

    @staticmethod
    def _make_patch_ds(
        source: ColumnDataSource,
        idx: int,
        pos: int,
        label: str,
        width: float,
    ) -> dict[str, Any]:
        norm = source.data["kde_x"][idx]
        grid = source.data["kde_y"][idx]
        xs = [pos - n * width for n in norm] + [pos + n * width for n in reversed(norm)]
        ys = list(grid) + list(reversed(grid))
        commits = [label] * len(xs)
        return {"x": xs, "y": ys, "commit": commits}

    @staticmethod
    def _render_violin(
        fig: figure,
        ds: ColumnDataSource,
        fill_color: str,
        legend_label: str,
    ) -> None:
        fig.patch(
            x="x",
            y="y",
            source=ds,
            fill_color=fill_color,
            fill_alpha=0.6,
            line_color="black",
            legend_label=legend_label,
        )

    @staticmethod
    def _add_median_spans(
        fig: figure,
        medians: list[float],
        i1: int,
        i2: int,
    ) -> tuple[Span, Span]:
        span1 = Span(
            location=medians[i1],
            dimension="width",
            line_color="blue",
            line_dash="dashed",
            line_width=2,
        )
        span2 = Span(
            location=medians[i2],
            dimension="width",
            line_color="red" if medians[i2] > medians[i1] else "green",
            line_dash="dashed",
            line_width=2,
        )
        fig.add_layout(span1)
        fig.add_layout(span2)
        return span1, span2

    @staticmethod
    def _add_diff_label(
        fig: figure,
        medians: list[float],
        i1: int,
        i2: int,
        source: ColumnDataSource,
    ) -> Label:
        delta = medians[i2] - medians[i1]
        y_max = max(source.data["kde_y"][i2])
        label = Label(
            x=0.5,
            y=y_max * 1.05,
            text=f"Δ median = {delta:.2f} J",
            text_align="center",
            text_font_size="12pt",
            text_color="red" if delta > 0 else "green",
        )
        fig.add_layout(label)
        return label

    @staticmethod
    def _configure_xaxis(
        fig: figure,
        label1: str,
        label2: str,
    ) -> None:
        ticker = FixedTicker(ticks=[0, 1])
        fig.xaxis[0].ticker = ticker
        fig.xaxis[0].major_label_overrides = {0: label1, 1: label2}
        fig.xaxis[0].axis_label = "Commit (short hash)"
