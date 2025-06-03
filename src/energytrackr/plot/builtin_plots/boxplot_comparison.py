"""This module implements the BoxplotComparison plot for energytrackr.

BoxplotComparison using BasePlot and composable mixins for cleaner architecture,
with notches, median-connecting line, and full/raw data sources restored.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from bokeh.models import ColumnDataSource, FactorRange, Range1d, Whisker
from bokeh.palettes import Category10
from bokeh.plotting import figure
from bokeh.transform import jitter

from energytrackr.plot.builtin_plots.mixins import (
    ComparisonBase,
    get_labels_and_dists,
    initial_commits,
)
from energytrackr.plot.builtin_plots.registry import register_plot
from energytrackr.plot.core.context import Context


@dataclass
class SingleStats:
    """Statistical summary for a commit: quartiles, whiskers, and notch bounds."""

    commit: str
    quartiles: tuple[float, float, float]  # Q1, median, Q3
    whiskers: tuple[float, float]  # lower, upper
    notch: tuple[float, float]  # lower, upper notch around the median


@register_plot
class BoxplotComparison(ComparisonBase):
    """Interactive boxplot comparison for two selected commits.

    - quartiles & whiskers
    - notches around medians
    - dashed line connecting medians
    - full & raw data sources for dynamic JS callbacks
    - tilted x-axis labels for readability
    """

    def __init__(self) -> None:
        """Initialize the BoxplotComparison plot."""
        self._stats: list[SingleStats] | None = None
        self._sources: dict[str, ColumnDataSource] | None = None

    def _make_figure(self, ctx: Context) -> figure:  # noqa: PLR6301
        labels, _ = get_labels_and_dists(ctx)
        init1, init2 = initial_commits(labels)

        fig = figure(
            x_range=FactorRange(*[init1, init2]),
            sizing_mode="stretch_width",
            tools="pan,box_zoom,reset,save,wheel_zoom",
            toolbar_location="above",
            title=f"Distribution Boxplot: {ctx.energy_fields[0]}",
            x_axis_label="Commit (short hash)",
            y_axis_label=f"{ctx.energy_fields[0]} (J)",
        )
        # tilt x-axis labels like the old version
        for axis in fig.xaxis:
            axis.major_label_orientation = 0.8
        return fig

    def _compute_stats(self, labels: list[str], dists: list[np.ndarray]) -> list[SingleStats]:  # noqa: PLR6301 # pylint: disable=too-many-locals
        stats: list[SingleStats] = []
        for lbl, arr in zip(labels, dists, strict=False):
            a = np.sort(np.asarray(arr, float))
            q1, med, q3 = np.percentile(a, [25, 50, 75])
            iqr = q3 - q1
            lower = max(a.min(), q1 - 1.5 * iqr)
            upper = min(a.max(), q3 + 1.5 * iqr)
            half_notch = 1.57 * iqr / np.sqrt(len(a))
            notch_low, notch_high = med - half_notch, med + half_notch
            stats.append(SingleStats(lbl, (q1, med, q3), (lower, upper), (notch_low, notch_high)))
        return stats

    def _make_sources(self, ctx: Context) -> dict[str, Any]:  # noqa: PLR0914 # pylint: disable=too-many-locals
        labels, dists = get_labels_and_dists(ctx)

        # compute stats for each commit, including notch
        stats = self._compute_stats(labels, dists)

        init1, init2 = initial_commits(labels)
        i1, i2 = labels.index(init1), labels.index(init2)
        vals1, vals2 = dists[i1], dists[i2]

        l1, u1 = stats[i1].whiskers
        l2, u2 = stats[i2].whiskers

        norm1 = [v for v in vals1 if l1 <= v <= u1]
        out1 = [v for v in vals1 if v < l1 or v > u1]
        norm2 = [v for v in vals2 if l2 <= v <= u2]
        out2 = [v for v in vals2 if v < l2 or v > u2]

        # build two new CDS's
        inlier_scatter = ColumnDataSource({
            "commit": [init1] * len(norm1) + [init2] * len(norm2),
            "value": norm1 + norm2,
        })
        outlier_scatter = ColumnDataSource({
            "commit": [init1] * len(out1) + [init2] * len(out2),
            "value": out1 + out2,
        })
        # full data source (all commits)
        full_src = ColumnDataSource({
            "commit": [s.commit for s in stats],
            "q1": [s.quartiles[0] for s in stats],
            "median": [s.quartiles[1] for s in stats],
            "q3": [s.quartiles[2] for s in stats],
            "lower": [s.whiskers[0] for s in stats],
            "upper": [s.whiskers[1] for s in stats],
            "n_low": [s.notch[0] for s in stats],
            "n_high": [s.notch[1] for s in stats],
        })

        # raw distributions source
        raw_src = ColumnDataSource({
            "commit": labels,
            "values": dists,
        })

        # color palette for the two boxes
        palette = Category10[3]
        colors = palette[:2]

        # box + notch + whisker source for initial pair
        box_src = ColumnDataSource({
            "commit": [init1, init2],
            "q1": [stats[i1].quartiles[0], stats[i2].quartiles[0]],
            "median": [stats[i1].quartiles[1], stats[i2].quartiles[1]],
            "q3": [stats[i1].quartiles[2], stats[i2].quartiles[2]],
            "lower": [stats[i1].whiskers[0], stats[i2].whiskers[0]],
            "upper": [stats[i1].whiskers[1], stats[i2].whiskers[1]],
            "n_low": [stats[i1].notch[0], stats[i2].notch[0]],
            "n_high": [stats[i1].notch[1], stats[i2].notch[1]],
            "color": colors,
        })

        # scatter sources for raw points
        scat1 = ColumnDataSource({"commit": [init1] * len(vals1), "value": vals1})
        scat2 = ColumnDataSource({"commit": [init2] * len(vals2), "value": vals2})

        # line source connecting medians
        line_src = ColumnDataSource({
            "x": [init1, init2],
            "y": [stats[i1].quartiles[1], stats[i2].quartiles[1]],
        })

        self._stats = stats
        self._sources = {
            "full": full_src,
            "raw": raw_src,
            "box": box_src,
            "scatter1": scat1,
            "scatter2": scat2,
            "line": line_src,
            "inlier_scatter": inlier_scatter,
            "outlier_scatter": outlier_scatter,
        }
        return self._sources

    def _draw_glyphs(self, fig: figure, sources: dict[str, ColumnDataSource], ctx: Context) -> None:  # noqa: ARG002
        box_src = sources["box"]

        # notch (thin bar around median)
        fig.vbar(
            x="commit",
            bottom="n_low",
            top="n_high",
            width=0.3,
            source=box_src,
            fill_color="color",
            fill_alpha=0.5,
            line_color="red",
            legend_label="Notch",
        )

        # box between Q1 and Q3
        fig.vbar(
            x="commit",
            bottom="q1",
            top="q3",
            width=0.6,
            source=box_src,
            fill_color="color",
            fill_alpha=0.3,
            line_color="black",
            legend_label="IQR box",
        )

        # whiskers
        whisk = Whisker(source=box_src, base="commit", lower="lower", upper="upper")
        upper_head = whisk.upper_head
        assert upper_head is not None
        upper_head.size = 8
        lower_head = whisk.lower_head
        assert lower_head is not None
        lower_head.size = 8
        fig.add_layout(whisk)

        # median ticks
        fig.rect(
            x="commit",
            y="median",
            width=0.6,
            height=1,
            height_units="screen",
            source=box_src,
            color="red",
            legend_label="Median",
        )

        # dashed line connecting the two medians
        fig.line(
            x="x",
            y="y",
            source=sources["line"],
            line_dash="dashed",
            line_color="firebrick",
            line_width=2,
            legend_label="Median trend",
        )

        # draw inliers lightly
        fig.circle(
            x=jitter("commit", width=0.3, range=fig.x_range),
            y="value",
            source=sources["inlier_scatter"],
            radius=0.01,  # small, subtle
            alpha=0.3,
            color="grey",
            legend_label="Inliers",
        )

        # draw outliers in bold
        fig.circle(
            x=jitter("commit", width=0.3, range=fig.x_range),
            y="value",
            source=sources["outlier_scatter"],
            radius=0.02,  # larger marker
            alpha=0.8,  # more opaque
            fill_color="firebrick",
            line_color="black",
            line_width=1,
            legend_label="Outliers",
        )

        # adjust y-range to include whiskers with margin
        assert self._stats is not None
        lows = [ws[0] for ws in (s.whiskers for s in self._stats)]
        highs = [ws[1] for ws in (s.whiskers for s in self._stats)]
        margin = (max(highs) - min(lows)) * 0.05
        fig.y_range = Range1d(start=min(lows) - margin, end=max(highs) + margin)

    def _title(self, ctx: Context) -> str:  # noqa: PLR6301
        return f"Distribution Boxplot: {ctx.energy_fields[0]}"

    def _key(self, ctx: Context) -> str:  # noqa: ARG002, PLR6301
        return "Boxplot"

    def _callback_js_path(self) -> Path:  # noqa: PLR6301
        return Path(__file__).parent / "static" / "boxplot_comparison.js"

    def _callback_args(self, fig: figure, ctx: Context) -> dict[str, Any]:  # noqa: ARG002
        # pass full/raw + box/scatter/line sources into JS callback
        assert self._sources is not None
        return {**self._sources, "plot": fig}

    def _hover_tooltips(self, ctx: Context) -> list[tuple[str, str]]:  # noqa: ARG002, PLR6301
        return [
            ("Commit", "@commit"),
            ("Q1", "@q1{0.00} J"),
            ("Median", "@median{0.00} J"),
            ("Q3", "@q3{0.00} J"),
            ("Lower", "@lower{0.00} J"),
            ("Upper", "@upper{0.00} J"),
        ]
