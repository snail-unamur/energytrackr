"""EnergyTrackr pipeline core.

Key architectural highlights
----------------------------
* **Strategy plug-in registry** - new strategies (e.g. *DFS*, *genetic*) can be
  added in a single class decorated with :pyfunc:`@register_strategy` - no core
  edits required.
* **StageGroup** (formerly *ContainerStage*) cleanly encapsulates a composite
  execution unit with optional *deduplication* and *parallelism*.
* **PipelineEngine** orchestrates StageGroups and delegates batching to a
  pluggable strategy; clear public surface for unit-testing.
* **Typed Context** remains but now supports mapping protocol fully.
* **Functional verticals** (strategy, execution, utils) live in isolated
  sections to avoid huge files and untangle import dependencies.

The module is self-contained; existing stage implementations continue to work
unchanged.  A downstream project can now extend the pipeline by simply adding
``energytrackr/pipeline/strategies/my_algo.py`` with a registered class.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from turtle import pos
from typing import Final

from git import Commit, GitError, Repo
from numpy import test
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from energytrackr.config.config_model import PipelineConfig
from energytrackr.config.config_store import Config
from energytrackr.config.loader import load_pipeline_config
from energytrackr.pipeline.context import Context
from energytrackr.pipeline.core_stages.build_stage import BuildStage
from energytrackr.pipeline.core_stages.checkout_stage import CheckoutStage
from energytrackr.pipeline.core_stages.copy_directory_stage import (
    CopyDirectoryStage,
)
from energytrackr.pipeline.core_stages.filter_and_regression_stage import (
    FilterAndRegressionStage,
)
from energytrackr.pipeline.core_stages.measure_stage import MeasureEnergyStage
from energytrackr.pipeline.core_stages.post_test_stage import PostTestStage
from energytrackr.pipeline.core_stages.set_directory_stage import SetDirectoryStage
from energytrackr.pipeline.core_stages.temperature_check_stage import (
    TemperatureCheckStage,
)
from energytrackr.pipeline.core_stages.verify_perf_stage import VerifyPerfStage
from energytrackr.pipeline.stage_interface import StageGroup

# from energytrackr.pipeline.strategies.bisection import BisectionStrategy  # noqa: F401 # pylint: disable=unused-import
# from energytrackr.pipeline.strategies.breadth_first import ThreePointStrategy  # noqa: F401  # pylint: disable=unused-import
# from energytrackr.pipeline.strategies.divide_conquer import DivideConquerStrategy  # noqa: F401 # pylint: disable=unused-import
from energytrackr.pipeline.strategies.naive import NaiveStrategy  # noqa: F401 # pylint: disable=unused-import
from energytrackr.pipeline.strategies.pruned_binary_segmentation import (
    PrunedBinarySegmentationStrategy,
)  # noqa: F401 # pylint: disable=unused-import
from energytrackr.pipeline.strategies.strategy_interface import (
    BatchStrategy,
    register_strategy,
)
from energytrackr.utils.exceptions import PipelineAbortError
from energytrackr.utils.git_utils import clone_or_open_repo, gather_commits
from energytrackr.utils.logger import logger

__all__: Final[tuple[str, ...]] = (
    "BatchStrategy",
    "Context",
    "PipelineAbortError",
    "PipelineEngine",
    "StageGroup",
    "measure",
    "register_strategy",
)


class PipelineEngine:
    """High-level orchestrator that drives all stages across commits."""

    def __init__(self, repo_path: Path | str, *, config: PipelineConfig) -> None:
        """Initialize the pipeline engine."""
        self.repo_path = Path(repo_path)
        self.config = config
        plan = config.execution_plan
        par = set(getattr(plan, "parallel_stages", []))

        # ------------------------ Stage graph ---------------------------
        self._pre_stage = StageGroup(
            "pre",
            [VerifyPerfStage(), FilterAndRegressionStage()],
            parallel="pre" in par,
        )
        self._setup_stage = StageGroup(
            "setup",
            [CopyDirectoryStage(), SetDirectoryStage(), CheckoutStage(), BuildStage()],
            parallel=False,
            deduplicate=True,
        )
        self._test_stage = StageGroup(
            "test",
            [TemperatureCheckStage(), SetDirectoryStage(), MeasureEnergyStage()],
            parallel="test" in par,
        )
        self._post_stage = StageGroup("post", [PostTestStage()], parallel="post" in par)

        self._strategy: BatchStrategy = BatchStrategy.from_config(config)
        self._build_blacklist: set[str] = set()

    def run(self, *, initial_commits: list[Commit] | None = None) -> None:
        """Execute the full **energy measurement pipeline**.

        Args:
            initial_commits: Optional list of commits to start with. If not
                provided, all commits in the repository will be gathered.
        """
        commits: list[Commit] = initial_commits or gather_commits(Repo(self.repo_path))

        # 1. Pre-stages
        self.run_pre_stages(commits)

        columns = [
            SpinnerColumn(style="green"),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=None, complete_style="cyan", finished_style="green"),
            TextColumn("[progress.percentage]{task.percentage:>5.1f}%"),
            TextColumn("{task.completed}/{task.total}", justify="right"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        ]

        with Progress(*columns, transient=True) as progress:
            region_task = progress.add_task("Regions", total=self._strategy.get_search_space(commits))
            while True:
                # 2. Create initial batches
                batches: list[list[Commit]] = self._strategy.create_batches(commits)

                batch_task = progress.add_task("Batches", total=len(batches))

                results: dict[str, list[float]] = {}
                for batch in batches:
                    contexts: list[Context] = [
                        Context(commit=c.hexsha, repo_path=str(self.repo_path), commits=[c.hexsha]) for c in batch
                    ]
                    # 1. Build stages
                    setup_task = progress.add_task("Setup", total=len(contexts))
                    self._setup_stage.execute_over(contexts, progress, task_id=setup_task)
                    progress.remove_task(setup_task)
                    # 2. Test stages
                    test_task = progress.add_task("Testing", total=len(contexts))
                    self._test_stage.execute_over(contexts, progress, task_id=test_task)
                    progress.remove_task(test_task)
                    # 3. Post stages
                    post_task = progress.add_task("Post-processing", total=len(contexts))
                    self._post_stage.execute_over(contexts, progress, task_id=post_task)
                    progress.remove_task(post_task)
                    # 4. Clean up cache
                    try:
                        self.clean_cache_dir(str(self.repo_path))
                    except Exception as exc:
                        logger.warning("Cache cleanup failed: %s", exc)
                    progress.update(batch_task, advance=1)

                    # 4. Collect results
                    for context in contexts:
                        if context["energy_value"] is None:
                            logger.warning("Commit %s has no energy value - skipping.", context.get_commit().hexsha)
                            continue
                        results.setdefault(context.get_commit().hexsha, []).append(context["energy_value"])

                    # 5. Update build blacklist
                    logger.debug("Batch %s results: %s", [c.hexsha for c in batch], results)
                    for c in batch:
                        if c.hexsha not in results:
                            self._build_blacklist.add(c.hexsha)

                progress.remove_task(batch_task)

                # 6. Check if we need to refine commits
                if not self._strategy.refine_commits(
                    commits,
                    results,
                    build_blacklist=self._build_blacklist,
                ):
                    logger.info("No new regions to explore - pipeline finished.")
                    break
                progress.update(region_task, advance=1)
        logger.info(
            "Pipeline finished - %s commits black-listed as unbuildable.",
            len(self._build_blacklist),
        )
        self._strategy.summarize()

    def run_pre_stages(self, commits: list[Commit]) -> None:
        """Run the pre-stages of the pipeline.

        Args:
            commits (list[Commit]): List of commits to process.
        """
        commits_str = [c.hexsha for c in commits]
        ctx_full = Context(commit=commits_str[0], repo_path=str(self.repo_path), commits=commits_str)
        self._pre_stage.run(ctx_full)
        if ctx_full.abort_pipeline:
            logger.error("Aborted during *pre* stage - bailing out.")
            return
        commits = list(ctx_full.get_commits() or commits)
        logger.info("%d commits remain after filters", len(commits))

    @staticmethod
    def clean_cache_dir(repo_path: str) -> None:
        """Remove all entries in the cache directory (siblings of the cloned repo) to free disk space.

        Given that repo_path points to:
            <project_dir>/.cache/.cache_<project_name>
        this will delete everything under `<project_dir>/.cache/` except the live repo folder.

        Args:
            repo_path (str): Absolute path to the cloned repository.
        """
        cache_dir = os.path.dirname(repo_path)
        if not os.path.isdir(cache_dir):
            logger.warning("Cache directory %s does not exist", cache_dir)
            return

        for entry in os.listdir(cache_dir):
            entry_path = os.path.join(cache_dir, entry)
            # skip the active repo clone itself
            if os.path.abspath(entry_path) == os.path.abspath(repo_path):
                continue
            if os.path.isdir(entry_path):
                try:
                    shutil.rmtree(entry_path)
                except Exception as e:
                    logger.warning("Failed to remove cache entry %s: %s", entry_path, e)
            else:
                os.remove(entry_path)
            logger.info("Removed cache entry: %s", entry_path)


def measure(config_path: str | Path) -> None:
    """High-level wrapper called by the *CLI* entry-point.

    Args:
        config_path: Path to the *TOML* pipeline configuration file.
    """
    load_pipeline_config(str(config_path))
    cfg_dir = Path(config_path).resolve().parent
    config = Config.get_config()

    # Clone/open repo under a dedicated *cache* directory
    cache_dir = cfg_dir / ".cache"
    cache_dir.mkdir(exist_ok=True)
    project_name = Path(config.repo.url).stem.lower()
    repo_path = cache_dir / f".cache_{project_name}"

    repo = clone_or_open_repo(repo_path, config.repo.url, config.repo.clone_options)
    logger.info("Repository ready at %s (branch: %s)", repo_path, config.repo.branch)

    engine = PipelineEngine(repo_path, config=config)
    try:
        engine.run()
    finally:
        # Attempt cleanup so that repeated runs start fresh
        try:
            repo.git.checkout(config.repo.branch)
        except GitError as exc:
            logger.warning("Could not checkout default branch for cleanup: %s", exc)
        shutil.rmtree(repo_path.parent, ignore_errors=True)
