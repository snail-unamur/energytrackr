"""Pipeline orchestrator for running stages on commits in a repository."""

from __future__ import annotations

import concurrent.futures
import os
import random
import shutil
import sys
from abc import ABC, abstractmethod
from typing import Any, override

import git
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
from energytrackr.pipeline.core_stages.build_stage import BuildStage
from energytrackr.pipeline.core_stages.checkout_stage import CheckoutStage
from energytrackr.pipeline.core_stages.copy_directory_stage import CopyDirectoryStage
from energytrackr.pipeline.core_stages.filter_and_regression_stage import FilterAndRegressionStage
from energytrackr.pipeline.core_stages.measure_stage import MeasureEnergyStage
from energytrackr.pipeline.core_stages.post_test_stage import PostTestStage
from energytrackr.pipeline.core_stages.set_directory_stage import SetDirectoryStage
from energytrackr.pipeline.core_stages.temperature_check_stage import TemperatureCheckStage
from energytrackr.pipeline.core_stages.verify_perf_stage import VerifyPerfStage
from energytrackr.pipeline.stage_interface import PipelineStage
from energytrackr.utils.git_utils import clone_or_open_repo, gather_commits
from energytrackr.utils.logger import logger


class ContainerStage(PipelineStage, ABC):
    """Pipeline stage that groups and runs multiple sub-stages, optionally in parallel."""

    def __init__(
        self,
        name: str,
        stages: list[PipelineStage],
        parallel: bool = False,
        deduplicate: bool = False,
    ) -> None:
        """Initialize a container stage.

        Args:
            name: Unique identifier for this container stage.
            stages: List of PipelineStage instances to execute.
            parallel: Whether to run this stage across contexts in parallel.
            deduplicate: Whether to deduplicate contexts before running.
        """
        self.name = name
        self._stages = stages
        self.parallel = parallel
        self.deduplicate = deduplicate

    def run(self, context: dict[str, Any]) -> None:
        """Execute each sub-stage on a single context.

        Args:
            context: Shared pipeline context for one commit.
        """
        # replace commit SHA with commit object
        if context.get("commit") and isinstance(context["commit"], str):
            repo = git.Repo(context["repo_path"])
            context["commit"] = repo.commit(context["commit"])
        logger.info("Running %s stage with %d sub-stages.", self.name, len(self._stages))
        for stage in self._stages:
            logger.info("Running %s stage: %s", self.name, stage.__class__.__name__)
            stage.run(context)
            if context.get("abort_pipeline"):
                logger.warning(
                    "Aborting at %s due to failure in %s.",
                    self.name,
                    stage.__class__.__name__,
                )
                return


class BatchStrategy(ABC):
    """Abstract strategy for dividing and refining commit batches."""

    @abstractmethod
    def create_batches(self, commits: list[git.Commit]) -> list[list[git.Commit]]:
        """Return the initial list of commits to process.

        Args:
            commits: List of all commits in the repository.

        Returns:
            A list of commits to be processed in the first batch.
        """

    @abstractmethod
    def refine_commits(
        self,
        full_commits: list[git.Commit],
        measured_results: list[tuple[git.Commit, Any]],
    ) -> list[git.Commit]:
        """Refine the list of commits based on measurement outcomes.

        Args:
            full_commits: List of all commits in the repository.
            measured_results: List of tuples containing commit and its measurement result.

        Returns:
            A list of commits to be processed in the next batch.
        """


class NaiveBatchStrategy(BatchStrategy):
    """Strategy that processes all commits in fixed-size batches without refinement."""

    def __init__(
        self,
        batch_size: int,
        num_runs: int,
        num_repeats: int,
        randomize: bool,
    ) -> None:
        """Initialize the naive batch strategy."""
        self.batch_size = batch_size
        self.num_runs = num_runs
        self.num_repeats = num_repeats
        self.randomize = randomize

    @override
    def create_batches(self, commits: list[git.Commit]) -> list[list[git.Commit]]:  # pylint: disable=missing-return-doc
        commit_batches = [commits[i : i + self.batch_size] for i in range(0, len(commits), self.batch_size)]
        batches: list[list[git.Commit]] = []
        for commit_batch in commit_batches:
            batch_tasks: list[git.Commit] = []
            runs_per_commit = self.num_runs * self.num_repeats
            for commit in commit_batch:
                batch_tasks.extend([commit] * runs_per_commit)
            if self.randomize:
                random.shuffle(batch_tasks)
            batches.append(batch_tasks)
        return batches

    @override
    def refine_commits(
        self,
        full_commits: list[git.Commit],
        measured_results: list[tuple[git.Commit, Any]],
    ) -> list[git.Commit]:  # pylint: disable=missing-return-doc
        return []


class ThreePointBatchStrategy(BatchStrategy):
    """Smart 3-point search strategy for regression detection."""

    def __init__(
        self,
        num_runs: int,
        num_repeats: int,
    ) -> None:
        """Initialize the three-point batch strategy."""
        self.num_runs = num_runs
        self.num_repeats = num_repeats

    @override
    def create_batches(self, commits: list[git.Commit]) -> list[list[git.Commit]]:  # pylint: disable=missing-return-doc
        min_commit_count = 3
        if (n := len(commits)) < min_commit_count:
            return [commits]
        return [[commits[0], commits[n // 2], commits[-1]]]

    @override
    def refine_commits(
        self,
        full_commits: list[git.Commit],
        measured_results: list[tuple[git.Commit, Any]],
    ) -> list[git.Commit]:  # pylint: disable=missing-return-doc
        baseline = measured_results[0][0]
        for commit, regression in measured_results[1:]:
            if regression:
                idx_base = full_commits.index(baseline)
                idx_curr = full_commits.index(commit)
                lo, hi = sorted((idx_base, idx_curr))
                return full_commits[lo : hi + 1]
        return []


class Pipeline:
    """Orchestrates a regression-aware energy measurement pipeline with stage-level parallelism."""

    def __init__(self, repo_path: str) -> None:
        """Initialize the pipeline.

        Args:
            repo_path: Path to the local repository clone.
        """
        self.repo_path = repo_path
        self.config: PipelineConfig = Config.get_config()

        plan = self.config.execution_plan
        parallel_stages = getattr(plan, "parallel_stages", [])

        # define stages with optional parallel execution
        self.pre_stage = ContainerStage(
            "pre",
            [VerifyPerfStage(), FilterAndRegressionStage()],
            parallel="pre" in parallel_stages,
        )
        self.setup_stage = ContainerStage(
            "setup",
            [CopyDirectoryStage(), SetDirectoryStage(), CheckoutStage(), BuildStage()],
            parallel=True,
            deduplicate=True,
        )
        self.test_stage = ContainerStage(
            "test",
            [TemperatureCheckStage(), SetDirectoryStage(), MeasureEnergyStage()],
            parallel="test" in parallel_stages,
        )
        self.post_stage = ContainerStage(
            "post",
            [PostTestStage()],
            parallel="post" in parallel_stages,
        )

        if getattr(plan, "search_strategy", "naive") == "three_point":
            self.strategy: BatchStrategy = ThreePointBatchStrategy(plan.num_runs, plan.num_repeats)
        else:
            self.strategy = NaiveBatchStrategy(
                plan.batch_size,
                plan.num_runs,
                plan.num_repeats,
                plan.randomize_tasks,
            )

    def _run_stage_on_contexts(
        self,
        stage: ContainerStage,
        contexts: list[dict[str, Any]],
        progress: Progress,
    ) -> None:
        """Execute a container stage across all contexts, optionally in parallel with progress.

        Args:
            stage: The ContainerStage to run.
            contexts: List of context dicts, one per commit.
        """
        if stage.deduplicate:
            seen = set()
            unique_ctxs = []
            for ctx in contexts:
                sha = ctx["commit"]
                if sha not in seen:
                    seen.add(sha)
                    unique_ctxs.append(ctx)
            contexts = unique_ctxs
        total = len(contexts)
        max_workers = getattr(self.config.execution_plan, "max_workers", os.cpu_count() or 1)

        if stage.parallel and total > 1:
            logger.info("Running %s stage in parallel.", stage.name)
            with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(stage.run, ctx) for ctx in contexts]
                task_id = progress.add_task(stage.name, total=total)
                for future in concurrent.futures.as_completed(futures):
                    future.result()
                    progress.update(task_id, advance=1)
        else:
            task_id = progress.add_task(stage.name, total=total)
            for ctx in contexts:
                stage.run(ctx)
                progress.update(task_id, advance=1)

    def run(self, initial_commits: list[git.Commit] | None = None) -> None:
        """Execute the pipeline according to the chosen strategy, with configurable stage-level parallelism.

        Args:
            initial_commits: Optional list of commits; otherwise gather full history.
        """
        commits = initial_commits or gather_commits(git.Repo(self.repo_path))

        # pre-stages on full commit list
        ctx_full = {"commits": commits, "repo_path": self.repo_path}
        self.pre_stage.run(ctx_full)
        if ctx_full.get("abort_pipeline"):
            logger.warning("Pipeline aborted during pre-stages.")
            return

        search_space = commits
        batches = self.strategy.create_batches(search_space)
        total_batches = len(batches)

        with Progress(
            SpinnerColumn(style="green"),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=None, complete_style="cyan", finished_style="green"),
            TextColumn("[progress.percentage]{task.percentage:>5.1f}%"),
            TextColumn("{task.completed:>4}/{task.total:<4}", justify="right"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            transient=True,
        ) as progress:
            task_id = progress.add_task("Pipeline batches", total=total_batches)
            for batch in batches:
                logger.info("Processing batch of %d commits.", len(batch))
                # prepare contexts per commit
                contexts = [
                    {
                        "commit": c.hexsha,
                        "repo_path": self.repo_path,
                        "build_failed": False,
                        "abort_pipeline": False,
                    }
                    for c in batch
                ]

                # run setup, test, post sequentially or in parallel
                for stage in (self.setup_stage, self.test_stage, self.post_stage):
                    self._run_stage_on_contexts(stage, contexts, progress)

                # collect regression results
                results: list[tuple[git.Commit, bool]] = []
                for ctx in contexts:
                    if ctx.get("abort_pipeline"):
                        sys.exit(1)
                    commit = ctx["commit"]
                    assert isinstance(commit, git.Commit)
                    regression = ctx.get("regression", False)
                    assert isinstance(regression, bool)
                    results.append((commit, regression))

                # refine for next iteration
                if not (search_space := self.strategy.refine_commits(commits, results)):
                    progress.update(task_id, advance=1)
                    break
                clean_cache_dir(self.repo_path)
                progress.update(task_id, advance=1)

        logger.info("Pipeline completed.")


def measure(config_path: str) -> None:
    """Main entrypoint: load config, clone repo, run pipeline, then cleanup.

    Args:
        config_path: Path to pipeline configuration file.
    """
    load_pipeline_config(config_path)
    # Retrieve the configuration folder
    config_folder = os.path.dirname(config_path)
    config = Config.get_config()

    # Set up directories and repository
    repo_path = setup_project_dirs(config, config_folder)
    repo = clone_or_open_repo(repo_path, config.repo.url, config.repo.clone_options)

    pipeline = Pipeline(repo_path)
    pipeline.run()

    repo.git.checkout(config.repo.branch)
    shutil.rmtree(os.path.dirname(repo_path), ignore_errors=True)


def setup_project_dirs(config: PipelineConfig, config_dir: str) -> str:
    """Set up project, cache directories and return their paths.

    Args:
        config (Config): The configuration object containing repository information.

    Returns:
        tuple[str, str, str]: Paths for project directory, cache directory, and repository path.
    """
    project_name = os.path.basename(config.repo.url).replace(".git", "").lower()
    cache_dir = os.path.join(config_dir, ".cache")
    logger.info("Setting up cache directory: %s", cache_dir)
    os.makedirs(cache_dir, exist_ok=True)
    repo_path = os.path.abspath(os.path.join(cache_dir, f".cache_{project_name}"))
    logger.info("Setting up project directories: %s", repo_path)
    return repo_path


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
        try:
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path)
            else:
                os.remove(entry_path)
            logger.info("Removed cache entry: %s", entry_path)
        except Exception as e:
            logger.warning("Failed to remove cache entry %s: %s", entry_path, e)
