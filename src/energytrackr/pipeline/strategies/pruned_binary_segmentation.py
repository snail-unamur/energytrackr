"""PrunedBinarySegmentationStrategy.

Efficient recursive region-based regression detection.
- Only measures left/right endpoints of regions to minimize builds.
- Splits regions recursively when a regression is detected.

Main flow:
    - While pending regions:
        - Select and batch endpoints for measurement
        - Collect results; skip blacklisted endpoints
        - For each region: prune, split, or record as leaf regression
"""

from __future__ import annotations

import math
import random
from statistics import median
from typing import Any, override

import git
from scipy.stats import mannwhitneyu

from energytrackr.pipeline.strategies.strategy_interface import BatchStrategy, register_strategy
from energytrackr.utils.logger import logger


@register_strategy("pruned_binary_segmentation")
class PrunedBinarySegmentationStrategy(BatchStrategy):
    """Recursively detects regressions by comparing only region endpoints.

    Skips black-listed (build-failed) commits by using the nearest neighbor.
    """

    def __init__(
        self,
        *,
        num_runs: int,
        min_region: int = 3,
        p_threshold: float = 0.05,
        percent_threshold: float = 3.0,
        randomize: bool = False,
    ) -> None:
        self._num_runs = num_runs
        self._min_region = min_region
        self._p_threshold = p_threshold
        self._percent_threshold = percent_threshold
        self._randomize = randomize

        # internal state
        self._commits: list[git.Commit] = []

        # pending regions to explore, stored as (left_index, right_index)
        self._pending_regions: list[tuple[int, int]] = []

        self._leaf_regressions: list[tuple[int, int, float, float, float, float]] = []
        self._iteration: int = 0

        # metrics & dedupe
        self._explored_regions_count: int = 0
        self._tested_commits: set[str] = set()

        self._measured_commits: dict[str, list[float]] = {}

    @classmethod
    def from_plan(cls, plan: Any) -> PrunedBinarySegmentationStrategy:
        return cls(
            num_runs=plan.num_runs,
            min_region=getattr(plan, "pbs_min_region", 3),
            p_threshold=getattr(plan, "pbs_p_threshold", 1),
            percent_threshold=getattr(plan, "pbs_percent_threshold", 3.0),
            randomize=plan.randomize_tasks,
        )

    @override
    def create_batches(self, commits: list[git.Commit]) -> list[list[git.Commit]]:
        self._iteration += 1
        # Base case
        if not self._pending_regions:
            self._commits = commits
            regions = []
            self._initial_zone_size = max(5, math.ceil(len(commits) / 10))
            for start in range(0, len(self._commits), self._initial_zone_size):
                end = min(start + self._initial_zone_size - 1, len(self._commits) - 1)
                self._pending_regions.append((start, end))
                regions.append(self._commits[start])
                regions.append(self._commits[end])
            logger.debug("Initial regions: %s", self._pending_regions)
            tmp = [regions * self._num_runs]
        # Return the regions to explore
        else:
            regions = []
            for left, right in self._pending_regions:
                if commits[left].hexsha not in self._measured_commits:
                    regions.append(commits[left])
                else:
                    logger.debug("Skipping left endpoint %s, already measured", commits[left].hexsha)
                if commits[right].hexsha not in self._measured_commits:
                    regions.append(commits[right])
                else:
                    logger.debug("Skipping right endpoint %s, already measured", commits[right].hexsha)
            tmp = [regions * self._num_runs]  # Return the endpoints of each region
        if self._randomize:
            random.shuffle(tmp)
        return tmp

    @override
    def refine_commits(
        self,
        full_commits: list[git.Commit],
        measured_results: dict[str, list[float]],
        *,
        build_blacklist: set[str],
    ) -> bool:
        """Refine the list of pending regions based on new measurements.

        Args:
            full_commits: The complete list of commits.
            measured_results: Mapping from commit hexsha to list of measured values.
            build_blacklist: Set of hexshas that failed to build.

        Returns:
            bool: True if there are still pending regions to explore, False otherwise.
        """
        self._iteration += 1
        # Cache measured commits
        for commit_hash, values in measured_results.items():
            self._measured_commits[commit_hash] = values.copy()

        next_pending_regions = []
        for left, right in self._pending_regions:
            # Get the commits at the left and right indices
            left_commit = full_commits[left]
            right_commit = full_commits[right]

            # If commit in build blacklist, find the nearest valid commit
            if left_commit.hexsha in build_blacklist or right_commit.hexsha in build_blacklist:
                logger.debug("Skipping region (%s, %s) due to build blacklist", left_commit.hexsha, right_commit.hexsha)
                if left_commit.hexsha in build_blacklist:
                    left += 1
                if right_commit.hexsha in build_blacklist:
                    right -= 1
                if right - left + 1 > self._min_region:
                    next_pending_regions.append((left, right))
                continue
            # Retrieve results
            left_commit_results = self._measured_commits.get(left_commit.hexsha, [])
            right_commit_results = self._measured_commits.get(right_commit.hexsha, [])

            # Prune regions based on results
            if not left_commit_results or not right_commit_results:
                logger.warning("Skipping region (%s, %s) due to missing measurements", left_commit.hexsha, right_commit.hexsha)
                continue
            median_left = median(left_commit_results)
            median_right = median(right_commit_results)

            # Compute percentage change
            pct_change = ((median_right - median_left) / median_left) * 100.0 if median_left != 0 else float("inf")

            # Perform Mann-Whitney U statistical test
            p_value_mw = 1.0
            if len(left_commit_results) > 1 and len(right_commit_results) > 1:
                try:
                    _, p_value_mw = mannwhitneyu(left_commit_results, right_commit_results, alternative="two-sided")
                except ValueError as e:
                    logger.error("Mann-Whitney U test failed for %s vs %s: %s", left_commit.hexsha, right_commit.hexsha, e)
            # Check if result is a regression
            if p_value_mw < self._p_threshold and abs(pct_change) >= self._percent_threshold:
                logger.debug(
                    "Region (%s, %s) detected as regression: p=%.4f, Δ=%.2f%%",
                    left_commit.hexsha[:8],
                    right_commit.hexsha[:8],
                    p_value_mw,
                    pct_change,
                )
                # Check if region can be split further
                if right - left + 1 > self._min_region:
                    logger.debug(
                        "Region (%s, %s) can be split further: size=%d, min_region=%d",
                        left_commit.hexsha[:8],
                        right_commit.hexsha[:8],
                        right - left + 1,
                        self._min_region,
                    )
                    # Split the region into two halves
                    mid = (left + right) // 2
                    next_pending_regions.append((left, mid))
                    next_pending_regions.append((mid + 1, right))

                else:
                    logger.debug(
                        "Region (%s, %s) is a leaf regression: size=%d, min_region=%d",
                        left_commit.hexsha[:8],
                        right_commit.hexsha[:8],
                        right - left + 1,
                        self._min_region,
                    )
                    # Record as a leaf regression
                    self._leaf_regressions.append((left, right, median_left, median_right, pct_change, p_value_mw))
            else:
                # Prune the region
                logger.debug(
                    "Region (%s, %s) not a regression: p=%.4f, Δ=%.2f%%",
                    left_commit.hexsha[:8],
                    right_commit.hexsha[:8],
                    p_value_mw,
                    pct_change,
                )
        self._pending_regions = next_pending_regions
        logger.debug("Refined regions: %d", len(self._pending_regions))
        logger.debug("Refined regions details: %s", self._pending_regions)
        return len(self._pending_regions) > 0

    def get_result(self) -> list[tuple[git.Commit, git.Commit, float, float, float, float]]:
        return [(self._commits[l], self._commits[r], la, ra, pct, p) for (l, r, la, ra, pct, p) in self._leaf_regressions]

    def progress_report(self, **kwargs) -> str:
        return f"PBS Iter {self._iteration}: {len(self._pending_regions)} regions, {len(self._leaf_regressions)} leaf regs"

    def summarize(self) -> None:
        if self._leaf_regressions:
            logger.info("Leaf regressions:")
            for left, right, la, ra, pct, p in self._leaf_regressions:
                c0, c1 = self._commits[left], self._commits[right]
                logger.info("%s → %s | %.2f→%.2f | Δ=%.2f%% | p=%.4f", c0.hexsha[:8], c1.hexsha[:8], la, ra, pct, p)
        else:
            logger.info("No leaf regressions detected.")

        logger.info("Summary metrics:")
        logger.info("  Iterations explored : %d", self._iteration)
        # logger.info("  Regions explored    : %d", self._explored_regions_count)
        logger.info("  Unique commits tested: %d", len(self._measured_commits))

    def get_search_space(self, commits: list[git.Commit]) -> int:
        return 1 if self._min_region <= 0 else len(commits) // self._min_region + 1
