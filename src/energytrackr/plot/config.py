# src/plot/config.py
"""Configuration module for plot module for EnergyTrackr."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from energytrackr.utils.exceptions import MissingEnergyTrackrKeyError, SettingsReadOnlyError
from energytrackr.utils.logger import logger


# ---------------------------------------------------------------------------
# Pydantic schema — every configurable knob is declared here
# ---------------------------------------------------------------------------
class ColumnCfg(BaseModel):
    """Configuration model for a table column in the plotting module.

    Attributes:
        key (str | None): The unique identifier for the column, typically corresponding to a data field.
        group (str | None): Optional group name to which this column belongs.
        label (str | None): Display label for the column header.
        width (str | None): Optional width specification for the column (e.g., '100px', '10%').
        align (Literal["left", "right", "center"] | None): Text alignment for the column content.
        fmt (str | None): Optional format string for displaying the column's values.
        include (Sequence[str]): Sequence of dataset names or contexts where this column should be included.
        exclude (Sequence[str]): Sequence of dataset names or contexts where this column should be excluded.
    """

    key: str | None = None
    group: str | None = None
    label: str | None = None
    width: str | None = None
    align: Literal["left", "right", "center"] | None = None
    fmt: str | None = None
    include: Sequence[str] = ()
    exclude: Sequence[str] = ()


class ReportCfg(BaseModel):
    """Configuration model for report settings.

    Attributes:
        theme (str): The theme to use for the report, e.g., "light" or "dark". Defaults to "light".
        chart (dict[str, Any]): Dictionary containing chart-specific configuration options.
    """

    theme: str = "light"
    font: str = "Roboto"
    font_size: int = 12
    chart: dict[str, Any] = Field(default_factory=dict)


class Thresholds(BaseModel):
    """Configuration model for statistical thresholds used in energy analysis.

    :no-index:

    Attributes:
        normality_p (float): Significance level for normality tests (default: 0.05).
        welch_p (float): Significance level for Welch's t-test (default: 0.05).
        min_pct_increase (float): Minimum percentage increase considered significant (default: 0.02).
        cohen_d (dict[str, float]): Dictionary mapping metric names to Cohen's d effect size thresholds.
        pct_change (dict[str, float]): Dictionary mapping metric names to percentage change thresholds.
        practical (dict[str, float]): Dictionary mapping metric names to practical significance thresholds.
    """

    normality_p: float = 0.05
    welch_p: float = 0.05
    min_pct_increase: float = 0.02
    min_values_for_normality_test: int = 3
    cohen_d: dict[str, float] = Field(
        default_factory=lambda: {
            "negligible": 0.2,
            "small": 0.5,
            "medium": 0.8,
            "large": 1.2,
        },
    )
    pct_change: dict[str, float] = Field(
        default_factory=lambda: {
            "minor": 0.05,
            "moderate": 0.10,
            "major": float("inf"),
        },
    )
    practical: dict[str, float] = Field(
        default_factory=lambda: {
            "info": 0.05,
            "warning": 0.1,
            "critical": 0.2,
        },
    )


class AnalysisCfg(BaseModel):
    """Configuration model for analysis steps and thresholds.

    Attributes:
        thresholds (Thresholds): An instance of the Thresholds class specifying threshold values for the analysis.
            Defaults to a new Thresholds instance.
    """

    thresholds: Thresholds = Thresholds()


class MetricCfg(BaseModel):
    """Configuration for a single analysis metric (column + display metadata).

    Attributes:
        column (str): The CSV column name to analyse.
        label (str): Human-readable label (e.g. "Package Energy", "Runtime").
        unit (str): Unit string appended to axis labels (e.g. "J", "s").
    """

    column: str
    label: str = ""
    unit: str = ""

    def model_post_init(self, __context: Any) -> None:  # noqa: ANN401
        """Default label and unit from column name if not provided."""
        if not self.label:
            object.__setattr__(self, "label", self.column)
        if not self.unit:
            object.__setattr__(self, "unit", self.column)


class DataCfg(BaseModel):
    """Configuration model for energy data plotting.

    Attributes:
        csv_columns (Sequence[str]): Tuple of column names expected in the CSV data,
                                     including commit identifier and energy measurements.
        energy_fields (Sequence[str]): Tuple of column names corresponding to energy measurement fields.
        metrics (list[MetricCfg]): Ordered list of metrics to analyse. When non-empty, drives the
            multi-metric pipeline loop. Defaults to empty (pipeline falls back to energy_fields[0]).
        min_measurements (int): Minimum number of measurements required for analysis.
        drop_outliers (bool): Whether to remove outlier data points based on the IQR method.
        outlier_iqr (float): The interquartile range (IQR) multiplier used to determine outliers.
    """

    csv_columns: Sequence[str] = ("commit", "energy-pkg", "energy-core", "energy-gpu")
    energy_fields: Sequence[str] = ("energy-pkg", "energy-core", "energy-gpu")
    metrics: list[MetricCfg] = Field(default_factory=list)
    min_measurements: int = 2
    drop_outliers: bool = True
    outlier_iqr: float = 1.5


class PlotCfg(BaseModel):
    """Configuration model for plotting.

    Attributes:
        transforms (Sequence[dict[str, Any]]): A sequence of transformation configurations to be applied to the plot data.
        objects (Sequence[dict[str, Any]]): A sequence of plot object configurations (e.g., lines, bars, markers).
        page (Sequence[dict[str, Any]]): A sequence of page-level configuration dictionaries (e.g., layout, titles).
    """

    transforms: Sequence[dict[str, Any]] = ()
    objects: Sequence[dict[str, Any]] = ()
    page: Sequence[dict[str, Any]] = ()
    plots: Sequence[dict[str, Any]] = ()


class EnergyTrackRCfg(BaseModel):
    """Configuration model for the EnergyTrackR application.

    This class aggregates the main configuration sections required for the application,
    including data handling, analysis, reporting, plotting, and plugins. Each section
    is represented by its own configuration model.

    Attributes:
        data (DataCfg): Configuration for data sources and preprocessing.
        analysis (AnalysisCfg): Settings for analysis routines and parameters.
        report (ReportCfg): Options for report generation and formatting.
        plot (PlotCfg): Plotting and visualization configuration.
        plugins (PluginsCfg): Plugin management and extension settings.
    """

    data: DataCfg = DataCfg()
    analysis: AnalysisCfg = AnalysisCfg()
    report: ReportCfg = ReportCfg()
    plot: PlotCfg = PlotCfg()


class Settings(BaseModel):
    """Facade imported by all modules: from plot.config import get_settings()."""

    energytrackr: EnergyTrackRCfg

    @classmethod
    def load(cls, path: Path | str | None = None) -> Settings:
        """Load the configuration settings from a YAML file.

        This class method attempts to load configuration data from the specified path.
        If no path is provided, it defaults to 'plot.yml' in the current working directory.
        If the file does not exist, it returns a Settings instance with built-in defaults.
        If the file exists, it parses the YAML content and expects a top-level 'energytrackr' key.
        Raises a KeyError if the required key is missing.
        If the configuration is invalid, logs the error and exits the program.

        Args:
            path (Path | str | None, optional): The path to the YAML configuration file.
                Defaults to None.

        Returns:
            Settings: An instance of the Settings class loaded with configuration data.

        Raises:
            MissingEnergyTrackrKeyError: If the top-level 'energytrackr' key is missing in the YAML file.
            SystemExit: If the configuration file is invalid.
        """
        cfg_path = Path(path) if path else Path.cwd() / "plot.yml"
        if not cfg_path.is_file():
            # fall back to built-in defaults if no YAML found
            return cls(energytrackr=EnergyTrackRCfg())
        raw = yaml.safe_load(cfg_path.read_text()) or {}
        if "energytrackr" not in raw:
            raise MissingEnergyTrackrKeyError()
        try:
            return cls(**raw)
        except ValidationError as exc:
            logger.error("❌  Invalid configuration file:\n%s", exc)
            raise SystemExit(1) from exc

    def __init__(self, **data: object) -> None:
        """Initializes the object with the provided data and freezes the instance to prevent further attribute reassignment.

        Args:
            **data (Any): Arbitrary keyword arguments used to initialize the object.

        """
        super().__init__(**data)
        # Freeze object so no one can reassign attributes
        object.__setattr__(self, "__frozen", True)

    def __setattr__(self, key: str, value: object) -> None:
        """Overrides the default attribute setting behavior.

        Prevents modification of attributes if the '_Settings__frozen' flag is set to True,
        raising an AttributeError to enforce read-only behavior. Otherwise, sets the attribute
        normally using the superclass implementation.

        Args:
            key (str): The name of the attribute to set.
            value (object): The value to assign to the attribute.

        Raises:
            SettingsReadOnlyError: If the instance is frozen and an attempt is made to modify an attribute.
        """
        if getattr(self, "_Settings__frozen", False):
            raise SettingsReadOnlyError()
        super().__setattr__(key, value)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_settings(path: Path | str | None = None) -> Settings:
    """Return the singleton Settings, loading + validating once.

    Subsequent calls ignore `path` and return the cached instance.

    Args:
        path (Path | str | None): Path to the YAML configuration file.
            If None, defaults to "plot.yml" in the current directory.

    Returns:
        Settings: An instance of the Settings class, containing
    """
    return Settings.load(path)
