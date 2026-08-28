"""Shared, mutable blackboard passed to every plug-in object."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from bokeh.plotting import figure

if TYPE_CHECKING:
    from energytrackr.plot.core.interfaces import PlotObj


@dataclass
class Context:
    """Context class holds the state and artefacts required for energy data analysis and plotting.

    Attributes:
        energy_data (EnergyData): The main energy data set to be analyzed or plotted.
        energy_column (str): The name of the column in energy_data representing energy values.
        artefacts (dict[str, Any]): Runtime artefacts produced by data transforms and plot objects.
        stats (dict[str, Any]): Statistical summaries or metrics computed during analysis.
        fig (figure | None): The figure object created by the pipeline and manipulated by plot objects.
        active_column (str): The column being analysed in the current pipeline iteration.
        active_unit (str): The unit string for active_column (e.g. "J", "s").
        active_label (str): The human-readable label for active_column.
    """

    input_path: str
    energy_fields: list[str]

    # Active metric set by the pipeline loop
    active_column: str = ""
    active_unit: str = ""
    active_label: str = ""

    # Runtime artefacts produced by transforms & plot objects
    artefacts: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)

    fig: figure | None = None  # created by pipeline, manipulated by objects
    plots: dict[str, Any] = field(default_factory=dict)
    plot_objects: dict[str, PlotObj] = field(default_factory=dict)
