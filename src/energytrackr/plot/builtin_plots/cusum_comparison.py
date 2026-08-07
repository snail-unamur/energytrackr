"""CUSUMComparison using BasePlot and mixins with refactored stats dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt
from bokeh.models import (
    CategoricalScale,
    ColumnDataSource,
    FactorRange,
    Label,
    LinearAxis,
    Range1d,
    Span,
)
from bokeh.plotting import figure

from energytrackr.plot.builtin_plots.mixins import FontMixin, HoverMixin, draw_additional_objects
from energytrackr.plot.builtin_plots.registry import register_plot
from energytrackr.plot.core.context import Context
from energytrackr.plot.core.interfaces import BasePlot, Configurable


@dataclass
class CUSJStats:
    """Joule-based CUSUM statistics."""

    cusum_pos_j: npt.NDArray[np.float64]
    cusum_neg_j: npt.NDArray[np.float64]
    cusum_net_j: npt.NDArray[np.float64]
    upper_j: float


@dataclass
class CUSPctStats:
    """Percentage-based CUSUM statistics."""

    cusum_pos_pct: npt.NDArray[np.float64]
    cusum_neg_pct: npt.NDArray[np.float64]
    cusum_net_pct: npt.NDArray[np.float64]
    upper_pct: float


@dataclass
class CUSStats:
    """All the series we need for CUSUM Comparison."""

    medians: npt.NDArray[np.float64]
    diffs: npt.NDArray[np.float64]
    sigma: float
    j: CUSJStats
    pct: CUSPctStats


@dataclass(frozen=True)
class CUSUMComparisonConfig:
    """Configuration for the CUSUMComparison plot."""

    objects: list[str] = field(default_factory=list)


@register_plot
class CUSUMComparison(FontMixin, HoverMixin, BasePlot, Configurable[CUSUMComparisonConfig]):
    """Enhanced CUSUM chart with both original areas and net-difference shading."""

    def __init__(self, **params: dict[str, Any]) -> None:
        """Initialize the CUSUMComparison plot with a list of plot objects."""
        super().__init__(CUSUMComparisonConfig, **params)
        self._stats: CUSStats | None = None
        self._src: ColumnDataSource | None = None

    def _make_figure(self, ctx: Context) -> figure:
        fig = super()._make_figure(ctx)
        labels = ctx.stats["short_hashes"]
        fig.x_range = FactorRange(*labels)
        fig.x_scale = CategoricalScale()

        for yaxis in fig.yaxis:
            yaxis.axis_label = "CUSUM (J)"

        # right-axis for percent
        fig.extra_y_ranges = {"pct": Range1d(start=0, end=100)}
        fig.add_layout(
            LinearAxis(y_range_name="pct", axis_label="CUSUM (%)"),
            "right",
        )
        return fig

    def _make_sources(self, ctx: Context) -> dict[str, Any]:
        stats = self._compute_stats(ctx.artefacts["distributions"])
        self._stats = stats

        labels = ctx.stats["short_hashes"]
        net_j = stats.j.cusum_net_j
        net_pos = np.where(net_j > 0, net_j, 0.0)
        net_neg = np.where(net_j < 0, net_j, 0.0)
        net_pct = stats.pct.cusum_net_pct

        data = {
            # original one-sided joules
            "pos_J": stats.j.cusum_pos_j.tolist(),
            "neg_J": stats.j.cusum_neg_j.tolist(),
            # net Joules masks
            "net_J": net_j.tolist(),
            "net_pos": net_pos.tolist(),
            "net_neg": net_neg.tolist(),
            # original one-sided percent
            "pos_pct": stats.pct.cusum_pos_pct.tolist(),
            "neg_pct": stats.pct.cusum_neg_pct.tolist(),
            # net percent
            "net_pct": net_pct.tolist(),
            # commit labels
            "commit": labels,
        }
        src = ColumnDataSource(data=data)
        self._src = src
        return {"src": src}

    def _draw_glyphs(self, fig: figure, sources: dict[str, ColumnDataSource], ctx: Context) -> None:
        src = sources["src"]
        stats = self._stats
        assert stats is not None

        # === ORIGINAL AREAS ===
        fig.varea(
            x="commit",
            y1="neg_J",
            y2=0,
            source=src,
            fill_color="green",
            fill_alpha=0.3,
            legend_label="Improvements",
        )
        fig.varea(
            x="commit",
            y1=0,
            y2="pos_J",
            source=src,
            fill_color="red",
            fill_alpha=0.3,
            legend_label="Regressions",
        )
        fig.line(
            x="commit",
            y="pos_pct",
            source=src,
            line_color="purple",
            line_width=2,
            y_range_name="pct",
        )
        fig.line(
            x="commit",
            y="neg_pct",
            source=src,
            line_color="teal",
            line_dash="dashed",
            line_width=2,
            y_range_name="pct",
        )

        # === NEW NET SHADING ===
        fig.varea(
            x="commit",
            y1="net_neg",
            y2=0,
            source=src,
            fill_color="green",
            fill_alpha=1.0,
            legend_label="Net Improvement",
        )
        fig.varea(
            x="commit",
            y1=0,
            y2="net_pos",
            source=src,
            fill_color="red",
            fill_alpha=1.0,
            legend_label="Net Regression",
        )
        fig.line(
            x="commit",
            y="net_J",
            source=src,
            line_color="black",
            line_width=2,
        )

        # === CONTROL LIMITS ===
        span_j = Span(
            location=stats.j.upper_j,
            dimension="width",
            line_dash="dashed",
            line_color="black",
            line_width=1,
        )
        fig.add_layout(span_j)
        span_pct = Span(
            location=stats.pct.upper_pct,
            dimension="height",
            line_dash="dashed",
            line_color="purple",
            line_width=1,
            y_range_name="pct",
        )
        fig.add_layout(span_pct)

        fig.add_layout(
            Label(
                x=0,
                y=stats.j.upper_j,
                text=f"±2sigma = {stats.j.upper_j:.1f} J",
                text_color="black",
                y_offset=5,
            ),
        )
        fig.add_layout(
            Label(
                x=len(stats.pct.cusum_net_pct) - 1,
                y=stats.pct.upper_pct,
                text=f"±2sigma = {stats.pct.upper_pct:.2f} %",
                text_color="purple",
                text_align="right",
                y_offset=5,
                y_range_name="pct",
            ),
        )
        for legend in fig.legend:
            legend.location = "top_left"

        draw_additional_objects(self.config.objects, fig, ctx)

    def _configure(self, fig: figure, ctx: Context) -> None:
        super()._configure(fig, ctx)
        stats = self._stats
        assert stats is not None

        for ax in fig.xaxis:
            ax.major_label_orientation = 0.8
            fig.xaxis[0].axis_label = "Commit (oldest → newest)"

        # set joule range
        peak_j = (
            max(
                stats.j.cusum_pos_j.max(),
                -stats.j.cusum_neg_j.min(),
                abs(stats.j.cusum_net_j).max(),
                stats.j.upper_j,
            )
            * 1.1
        )
        fig.y_range = Range1d(start=-peak_j, end=peak_j)

        # percent range
        peak_pct = (
            max(
                stats.pct.cusum_pos_pct.max(),
                -stats.pct.cusum_neg_pct.min(),
                abs(stats.pct.cusum_net_pct).max(),
                stats.pct.upper_pct,
            )
            * 1.1
        )
        pct_range = fig.extra_y_ranges["pct"]
        assert isinstance(pct_range, Range1d)
        pct_range.start = -peak_pct
        pct_range.end = peak_pct

    @staticmethod
    def _compute_stats(dists: list[list[float]]) -> CUSStats:
        med = np.array([float(np.median(a)) for a in dists], dtype=float)
        diffs = np.diff(med, prepend=med[0])

        # one-sided joules
        cus_pos_j = np.cumsum(np.clip(diffs, 0, None))
        cus_neg_j = np.cumsum(np.clip(diffs, None, 0))
        cus_net_j = cus_pos_j + cus_neg_j
        # percent
        pct_step = diffs / med[0] * 100
        pos_pct = np.where(pct_step > 0, pct_step, 0.0)
        neg_pct = np.where(pct_step < 0, pct_step, 0.0)
        cus_pos_pct = np.cumsum(pos_pct)
        cus_neg_pct = np.cumsum(neg_pct)
        cus_net_pct = cus_pos_pct + cus_neg_pct

        sigma = float(np.std(diffs))

        j_stats = CUSJStats(
            cusum_pos_j=cus_pos_j,
            cusum_neg_j=cus_neg_j,
            cusum_net_j=cus_net_j,
            upper_j=2 * sigma,
        )
        pct_stats = CUSPctStats(
            cusum_pos_pct=cus_pos_pct,
            cusum_neg_pct=cus_neg_pct,
            cusum_net_pct=cus_net_pct,
            upper_pct=(2 * sigma) / med[0] * 100,
        )

        return CUSStats(
            medians=med,
            diffs=diffs,
            sigma=sigma,
            j=j_stats,
            pct=pct_stats,
        )

    def _hover_tooltips(self, ctx: Context) -> list[tuple[str, str]]:  # noqa: ARG002, PLR6301
        return [
            ("Commit", "@commit"),
            ("Reg J", "@pos_J{0.0}"),
            ("Imp J", "@neg_J{0.0}"),
            ("Net J", "@net_J{0.0}"),
            ("Reg %", "@pos_pct{0.00}%"),
            ("Imp %", "@neg_pct{0.00}%"),
            ("Net %", "@net_pct{0.00}%"),
        ]

    def _title(self, ctx: Context) -> str:  # noqa: PLR6301
        return f"CUSUM Comparison - {ctx.active_column}"

    def _key(self, ctx: Context) -> str:  # noqa: ARG002, PLR6301
        return "CUSUM"
