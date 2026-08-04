"""EnergyTrackr: BatchStrategy interface.

This module defines the interface for batch strategies used in the EnergyTrackr pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, ClassVar

import git
from git import Commit

from energytrackr.config.config_model import PipelineConfig
from energytrackr.utils.logger import logger

_STRATEGY_REGISTRY: dict[str, type[BatchStrategy]] = {}


def register_strategy(name: str) -> Callable[..., type[BatchStrategy]]:
    """Class decorator to *register* a :class:`BatchStrategy` under *name*.

    Args:
        name (str): Name of the strategy to register.

    Returns:
        Callable[..., type[BatchStrategy]]: Decorator function that registers the strategy.
    """

    def _decorator(cls: type[BatchStrategy]) -> type[BatchStrategy]:
        if name in _STRATEGY_REGISTRY:
            raise ValueError(f"Duplicate strategy name: {name}")
        _STRATEGY_REGISTRY[name] = cls
        cls.__strategy_name__ = name
        return cls

    return _decorator


class BatchStrategy(ABC):
    """Policy object deciding **which commits to measure next**."""

    #: Name injected via decorator - useful for diagnostics
    __strategy_name__: ClassVar[str]

    @classmethod
    def from_config(cls, cfg: PipelineConfig) -> BatchStrategy:
        """Instantiate the strategy specified by *cfg.execution_plan*.

        Falls back to *naive* when unspecified.

        Args:
            cfg (PipelineConfig): The pipeline configuration object.

        Returns:
            BatchStrategy: The strategy object to use for the current pipeline.

        Raises:
            ValueError: If the strategy name is not recognized.
        """
        plan = cfg.execution_plan
        name = getattr(plan, "search_strategy", "naive")
        logger.debug("Using strategy: %s", name)
        logger.debug("strategies: %s", _STRATEGY_REGISTRY)
        try:
            klass = _STRATEGY_REGISTRY[name]
        except KeyError as exc:
            available = ", ".join(sorted(_STRATEGY_REGISTRY))
            raise ValueError(f"Unknown strategy '{name}'. Available: {available}") from exc
        return klass.from_plan(plan)

    @classmethod
    @abstractmethod
    def from_plan(cls, plan: Any) -> BatchStrategy:
        """Factory from *execution_plan* section of config."""

    @abstractmethod
    def create_batches(self, commits: list[git.Commit]) -> list[list[git.Commit]]:
        """Return list of *batches* covering the current *search-space*.

        Args:
            commits (list[git.Commit]): List of commits to be batched.

        Returns:
            list[list[git.Commit]]: List of batches, each containing a list of commits.
        """

    @abstractmethod
    def refine_commits(
        self,
        full_commits: list[git.Commit],
        measured_results: dict[str, list[float]],
        *,
        build_blacklist: set[str],
    ) -> bool:
        """Return new *regions* that still need exploration.

        Args:
            full_commits (list[git.Commit]): List of all commits.
            measured_results (dict[Commit, list[float]]): Dictionary containing
                commit and its corresponding result.
            build_blacklist (set[str]): Set of blacklisted commits.

        Returns:
            list[list[git.Commit]]: List of new regions to explore.
        """

    def get_result(self) -> object | None:
        """Return strategy-specific search result (default: None)."""
        return None

    def progress_report(self, *, iteration: int = 0, regions: list[list[git.Commit]] | None = None, **kwargs) -> str:
        """
        Optionally provide a human-readable progress string for logging/monitoring.
        Called once per main iteration.
        """
        return ""

    @abstractmethod
    def get_search_space(self, commits: list[Commit]) -> int:
        """Return the maximum number of search regions or iterations for this strategy.

        Args:
            commits (list[Commit]): The list of commits in the search space.

        Returns:
            int: The maximum number of regions or iterations.
        """
        raise NotImplementedError("This method should be implemented by subclasses.")
