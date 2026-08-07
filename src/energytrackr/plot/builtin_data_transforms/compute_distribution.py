# builtin_data_transforms/compute_distribution.py
"""Compute the distribution of a given column for each commit."""

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import shapiro

from energytrackr.plot.core.context import Context
from energytrackr.plot.core.interfaces import Configurable, Transform


@dataclass(frozen=True)
class ComputeDistributionConfig:
    """Configuration for computing distributions of energy measurements."""

    column: str | None = None
    min_values_for_normality: int = 3
    normality_p: float = 0.05


class ComputeDistribution(Transform, Configurable[ComputeDistributionConfig]):
    """Compute the distribution of a given column for each commit.

    From ctx.stats['valid_commits'] and ctx.artefacts['df'], build `distributions`
    and `normality_flags` in ctx.artefacts.
    """

    def __init__(self, **params: dict[str, Any]) -> None:
        """Initialize the compute distribution with configuration parameters."""
        super().__init__(ComputeDistributionConfig, **params)

    def apply(self, ctx: Context) -> None:
        """Computes and stores the value distributions and normality flags for each commit.

        For each commit in the provided context, extracts the values of the specified column,
        computes their distribution, and tests for normality using the Shapiro-Wilk test if
        the number of values meets the minimum threshold. The results are stored in the context's
        artefacts under "distributions" and "normality_flags".

        Args:
            ctx (Context): The context object containing artefacts, statistics, and configuration.

        Side Effects:
            Updates ctx.artefacts with:
                - "distributions": List of numpy arrays, each containing the values for a commit.
                - "normality_flags": List of booleans indicating if the distribution is normal (True)
                  or not (False) for each commit.
        """
        df = ctx.artefacts["df"]
        commits = ctx.stats["valid_commits"]
        col = self.config.column or ctx.active_column or ctx.energy_fields[0]
        min_for_sw = self.config.min_values_for_normality
        alpha = self.config.normality_p

        dists: list[np.ndarray] = []
        flags = []
        for c in commits:
            vals = df[df["commit"] == c][col].values.astype(float)
            dists.append(vals)
            if len(vals) >= min_for_sw:
                flags.append(shapiro(vals)[1] >= alpha)
            else:
                flags.append(True)
        ctx.artefacts["distributions"] = dists
        ctx.artefacts["normality_flags"] = flags
