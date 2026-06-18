# src/energytrackr/plot_new/builtin_transforms/load_csv.py
"""Load a CSV file into a DataFrame."""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from energytrackr.plot.config import get_settings
from energytrackr.plot.core.context import Context
from energytrackr.plot.core.interfaces import Configurable, Transform
from energytrackr.utils.logger import logger


@dataclass(frozen=True)
class LoadCSVConfig:
    """Configuration for loading a CSV file into a DataFrame."""

    csv_columns: list[str] = field(default_factory=list)
    has_header: bool = True


class LoadCSV(Transform, Configurable[LoadCSVConfig]):
    """Loads the CSV at ctx.input_path into ctx.artefacts['df'].

    - If `csv_columns` is passed via params or constructor, uses that list.
    - Otherwise falls back to settings.energytrackr.data.csv_columns.
    """

    def __init__(self, **params: dict[str, Any]) -> None:
        """Initialize the LoadCSV transform.

        Args:
            **params: Configuration parameters for loading the CSV file.
        """
        super().__init__(LoadCSVConfig, **params)

    def apply(self, ctx: Context) -> None:
        """Load the CSV file into a DataFrame and store it in ctx.artefacts['df'].

        The CSV file is read from ctx.input_path, and the DataFrame is created with the specified
        column names. If no column names are provided, defaults to the settings defined in
        settings.energytrackr.data.csv_columns.
        The DataFrame is then stored in ctx.artefacts['df'] for further processing.

        Args:
            ctx (Context): The context object containing the input path and artefacts.
        """
        # 1) pick up default or override
        if self.config.has_header:
            logger.info("Loading CSV file '%s' with header row", ctx.input_path)
            df = pd.read_csv(ctx.input_path, header=0)
        else:
            columns = self.config.csv_columns
            if not columns:
                cfg = get_settings().energytrackr.data
                columns = list(cfg.csv_columns)
            logger.info("Loading CSV file '%s' with columns: %s", ctx.input_path, columns)
            df = pd.read_csv(ctx.input_path, header=None, names=columns)

        # 2) stash for downstream transforms
        ctx.artefacts["df"] = df
