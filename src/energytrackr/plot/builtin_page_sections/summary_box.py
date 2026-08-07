"""SummaryBox - first HTML section in the default report.

Renders a quick statistics overview for the active energy column.  Uses a Jinja
partial `summary_box.html` that ships with *plot*; users can override by
encoding their own PageObj in YAML.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from jinja2 import Environment

from energytrackr.plot.core.context import Context
from energytrackr.plot.core.interfaces import Configurable, PageObj
from energytrackr.utils.logger import logger
from energytrackr.utils.utils import get_local_env


@dataclass(frozen=True)
class SummaryBoxConfig:
    """Configuration for the SummaryBox page section."""

    template: str = str(Path(__file__).with_name("templates") / "summary_box.html")


class SummaryBox(PageObj, Configurable[SummaryBoxConfig]):
    """Render general & statistical summary values."""

    def __init__(self, **params: dict[str, Any]) -> None:
        """Initialize the SummaryBox with a template path."""
        super().__init__(SummaryBoxConfig, **params)

    @property
    def template_path(self) -> str:
        """Get the path to the template file."""
        return self.config.template

    def render(self, env: Environment, ctx: Context) -> str:
        """Renders the summary box using a Jinja2 template.

        This method checks if the specified template file exists. If not, it logs an error and returns an HTML error message.
        If the template is outside the default environment's loader path, it creates a new Jinja2 Environment with the
        appropriate loader.
        It then loads the template, computes the overall summary for the first energy field in the context, and renders the
        template with the computed summary and the column name.

        Args:
            env (Environment): The Jinja2 environment to use for template rendering.
            ctx (Context): The context containing energy fields and other relevant data.

        Returns:
            str: The rendered HTML string for the summary box, or an error message if the template is missing.
        """
        if not Path(self.template_path).is_file():
            logger.error("SummaryBox: template '%s' not found.", self.template_path)
            return "<p><strong>Error:</strong> summary template missing.</p>"

        tmpl = get_local_env(env, self.template_path).get_template(Path(self.template_path).name)
        col = ctx.active_column or ctx.energy_fields[0]
        unit = ctx.active_unit or "J"
        label = ctx.active_label or col
        summary = self._compute_overall_summary(col, ctx)
        return tmpl.render(column=col, active_unit=unit, active_label=label, **summary)

    @staticmethod
    def _compute_overall_summary(energy_column: str, ctx: Context) -> dict[str, Any]:
        """Compute an overall summary of energy-related statistics for a given column.

        Args:
            energy_column (str): The name of the column containing energy data.
            ctx (Context): The context containing artefacts and statistics.

        Returns:
            dict: A dictionary containing the following summary statistics:
                - total_commits (int): Total number of data points in the distribution.
                - significant_changes (int): Number of significant change events.
                - regressions (int): Count of changes with an "increase" direction.
                - improvements (int): Count of changes with a "decrease" direction.
                - mean_energy (float): Mean value of the energy column.
                - median_energy (float): Median value of the energy column.
                - std_energy (float): Standard deviation of the energy column.
                - max_increase (float): Maximum severity of "increase" changes.
                - max_decrease (float): Maximum severity of "decrease" changes.
                - avg_cohens_d (float): Average absolute Cohen's d value for changes.
                - normal_count (int): Number of normality flags set to True.
                - non_normal_count (int): Number of normality flags set to False.
                - outliers_removed (int): Number of outliers removed from the dataset.
        """
        normality = ctx.artefacts["normality_flags"]
        changes = ctx.artefacts["change_events"]
        if (df := ctx.artefacts.get("df", pd.DataFrame())) is not None:
            outliers_removed_count = ctx.stats.get("commits_removed", 0)
            mean_energy = df[energy_column].mean()
            median_energy = df[energy_column].median()
            std_energy = df[energy_column].std()
        else:
            outliers_removed_count = 0
            mean_energy = None
            median_energy = None
            std_energy = None
        valid_commits = ctx.stats["valid_commits"]
        oldest_commit = valid_commits[-1] if valid_commits else None
        latest_commit = valid_commits[0] if valid_commits else None

        summary = {
            "project_name": ctx.artefacts["project_name"],
            "oldest_commit_hash": oldest_commit[:7] if oldest_commit else None,
            "oldest_commit_date": ctx.artefacts["commit_details"].get(oldest_commit, {}).get("commit_date")
            if oldest_commit
            else None,
            "latest_commit_hash": latest_commit[:7] if latest_commit else None,
            "latest_commit_date": ctx.artefacts["commit_details"].get(latest_commit, {}).get("commit_date")
            if latest_commit
            else None,
            "total_commits": len(ctx.stats["valid_commits"]),
            "significant_changes": sum(1 for e in changes if e.level > 0 and e.direction == "increase")
            + sum(1 for e in changes if e.level > 0 and e.direction == "decrease"),
            "regressions": sum(1 for e in changes if e.level > 0 and e.direction == "increase"),
            "improvements": sum(1 for e in changes if e.level > 0 and e.direction == "decrease"),
            "mean_energy": mean_energy,
            "median_energy": median_energy,
            "std_energy": std_energy,
            "avg_cohens_d": np.mean([abs(e.effect_size.cohen_d) for e in changes]) if changes else 0.0,
            "normal_count": sum(normality),
            "non_normal_count": len(normality) - sum(normality),
            "outliers_removed": outliers_removed_count,
        }
        return summary
