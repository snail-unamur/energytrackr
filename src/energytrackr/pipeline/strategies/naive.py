"""Naive energy regression search strategy."""

from __future__ import annotations

import random
from typing import Any, override

import git

from energytrackr.pipeline.strategies.strategy_interface import BatchStrategy, register_strategy


@register_strategy("naive")
class NaiveStrategy(BatchStrategy):
    """Fixed-size window, optionally shuffled; **no iterative refinement**."""

    def __init__(
        self,
        *,
        batch_size: int,
        num_runs: int,
        num_repeats: int,
        randomize: bool = False,
    ) -> None:
        """Initialize naive strategy."""
        self._batch_size = batch_size
        self._num_runs = num_runs
        self._num_repeats = num_repeats
        self._randomize = randomize

    @classmethod
    @override
    def from_plan(cls, plan: Any) -> NaiveStrategy:
        """Create a NaiveStrategy from a plan.

        Args:
            plan: The plan object containing the strategy configuration.

        Returns:
            NaiveStrategy: An instance of NaiveStrategy.
        """
        return cls(
            batch_size=plan.batch_size,
            num_runs=plan.num_runs,
            num_repeats=plan.num_repeats,
            randomize=plan.randomize_tasks,
        )

    @override
    def create_batches(self, commits: list[git.Commit]) -> list[list[git.Commit]]:
        """Create batches of commits for processing.

        Args:
            commits: A list of git commits to be batched.

        Returns:
            A list of batches, where each batch is a list of git commits.
        """
        runs_per_commit = self._num_runs * self._num_repeats
        batches: list[list[git.Commit]] = []
        for i in range(0, len(commits), self._batch_size):
            window = commits[i : i + self._batch_size]
            expanded = [c for c in window for _ in range(runs_per_commit)]
            if self._randomize:
                random.shuffle(expanded)
            batches.append(expanded)
        return batches

    @override
    def refine_commits(
        self,
        full_commits: list[git.Commit],
        measured_results: list[tuple[git.Commit, float | None]],
        *,
        build_blacklist: set[str],
    ) -> list[list[git.Commit]]:
        """Refine the list of commits based on measured results.

        This strategy does not refine commits, so it returns an empty list.

        Args:
            full_commits: The list of all commits.
            measured_results: The results of the measurements.
            build_blacklist: A set of commit SHAs to exclude from future builds.

        Returns:
            list[list[git.Commit]]: An empty list, as this strategy does not refine commits.
        """
        return []  # naive strategy never refines

    @override
    def get_search_space(self, commits: list[git.Commit]) -> int:
        """Return the maximum number of search regions or iterations for this strategy.

        Args:
            commits: The list of commits in the search space.

        Returns:
            int: The maximum number of regions or iterations.
        """
        return 1
