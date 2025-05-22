"""Energy‑aware measurement pipeline with regression‑driven bisection.

This module rewrites and extends the original proof‑of‑concept so that it may be
used in production research workloads.  Key improvements:

* **Configurable commit filtering** – honours the possibly‑mutated commit list
  produced by ``FilterAndRegressionStage``.
* **Robust build‑failure handling** – commits that fail to build once are
  black‑listed for the remainder of the run.  They will never be scheduled
  again, guaranteeing progress.
* **Early aborts without ``sys.exit``** – a dedicated :class:`PipelineAbort`
  exception unwinds the call‑stack so that outer layers can still perform
  cleanup.
* **Normality re‑sampling** – if either baseline or pivot fails a D’Agostino
  normality test, the algorithm enqueues the region for an *additional* round
  of measurements; eventually the central‑limit theorem should rescue us.
* **Neighbour substitution for broken pivots** – when a selected pivot cannot
  be compiled, an adjacent commit that *does* build is substituted.

The public surface remains *roughly* compatible with the original: the module
exposes an :func:`measure` helper that loads a pipeline config, clones the
repository, and drives the :class:`Pipeline` orchestration class.
"""

from __future__ import annotations

import concurrent.futures
import os
import random
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import git
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from scipy.stats import normaltest, ttest_ind

from energytrackr.config.config_model import PipelineConfig
from energytrackr.config.config_store import Config
from energytrackr.config.loader import load_pipeline_config
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
from energytrackr.pipeline.stage_interface import PipelineStage
from energytrackr.utils.git_utils import clone_or_open_repo, gather_commits
from energytrackr.utils.logger import logger

###############################################################################
# Exceptions
###############################################################################


class PipelineAbort(RuntimeError):
    """Raised when a *stage* requests an immediate shutdown of the pipeline."""


###############################################################################
# Context object – typed view over the shared dict                        #####
###############################################################################


@dataclass(slots=False, kw_only=True)
class Context:  # pylint: disable=too-many-instance-attributes
    """Runtime context passed to every :class:`PipelineStage`.

    Attributes
    ----------
    commit
        The Git *commit* currently under test.  May start out as a *str* SHA but
        is converted to a :class:`git.Commit` before any user code sees it.
    repo_path
        Absolute path to the cloned working directory.
    commits
        **New** optional list of Git commits (populated by FilterAndRegressionStage).
    energy_value
        Optional floating-point energy value produced by
        :class:`~energytrackr.pipeline.core_stages.measure_stage.MeasureEnergyStage`.
    build_failed
        *True* when :class:`BuildStage` could not build the project at this
        commit.
    abort_pipeline
        *True* when any stage enforces a hard stop.
    """

    commit: git.Commit | str
    repo_path: Path | str
    commits: list[git.Commit] | None = None
    energy_value: float | None = None
    build_failed: bool = False
    abort_pipeline: bool = False
    worker_process: bool = False

    # ---------------------------------------------------------------------
    # Convenience helpers
    # ---------------------------------------------------------------------

    def ensure_resolved(self) -> None:
        """Convert a SHA string into a :class:`git.Commit` object *in-place*."""
        if isinstance(self.commit, str):
            repo = git.Repo(self.repo_path)
            self.commit = repo.commit(self.commit)

    # ---------------------------------------------------------------------
    # Backwards compatibility for dict-like access
    # ---------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        """Dict-like get support for legacy stages."""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """Dict-like access for legacy stages."""
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        """Dict-like assignment for legacy stages."""
        setattr(self, key, value)

    def __contains__(self, key: str) -> bool:
        """Support for `key in context` patterns."""
        return hasattr(self, key)

    def setdefault(self, key: str, default: Any = None) -> Any:
        """Dict-like setdefault support for legacy stages."""
        if not hasattr(self, key):
            setattr(self, key, default)
            return default
        return getattr(self, key)


###############################################################################
# Stage containers                                                       #####
###############################################################################


class ContainerStage(PipelineStage):
    """A *composite* stage that runs a sequence of sub‑stages.

    Parameters
    ----------
    name
        Human‑readable identifier (used in logs / progress bars).
    stages
        Ordered collection of :class:`PipelineStage` implementations.
    parallel
        Attempt parallel execution (process pool) when *True*.
    deduplicate
        When *True*, only the *first* context for a given commit SHA is
        executed – handy for build stages.
    """

    def __init__(
        self,
        name: str,
        stages: Sequence[PipelineStage],
        *,
        parallel: bool = False,
        deduplicate: bool = False,
    ) -> None:
        self.name = name
        self.stages: list[PipelineStage] = list(stages)
        self.parallel = parallel
        self.deduplicate = deduplicate

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, context: Context) -> None:  # noqa: D401 – imperative mood
        """Run every sub‑stage sequentially **on the given context**.

        The method is intentionally *sequential*; parallelism is handled one
        layer up where multiple *contexts* are available.
        """
        context.ensure_resolved()
        logger.debug("[%s] start", self.name)
        for stage in self.stages:
            stage.run(context)  # may mutate *context*
            if context.abort_pipeline:
                logger.error("[%s] abort requested by %s", self.name, stage.__class__.__name__)
                raise PipelineAbort from None
        logger.debug("[%s] done", self.name)


###############################################################################
# Batch selection strategies                                             #####
###############################################################################


class BatchStrategy(ABC):
    """Policy object that decides **which commits to measure next**."""

    @abstractmethod
    def create_batches(self, commits: list[git.Commit]) -> list[list[git.Commit]]:  # noqa: D401
        """Return a list of *batches* covering the *current* search‑space."""

    @abstractmethod
    def refine_commits(  # noqa: D401
        self,
        full_commits: list[git.Commit],
        measured_results: list[tuple[git.Commit, float | None]],
        *,
        build_blacklist: set[str],
    ) -> list[list[git.Commit]]:
        """Return new regions that still need exploration."""


###############################################################################
# Naive – unchanged except for typing tweaks                             #####
###############################################################################


class NaiveBatchStrategy(BatchStrategy):
    """Fixed‑size window, possibly shuffled; **no iterative refinement**."""

    def __init__(
        self,
        batch_size: int,
        num_runs: int,
        num_repeats: int,
        randomize: bool = False,
    ) -> None:
        self.batch_size = batch_size
        self.num_runs = num_runs
        self.num_repeats = num_repeats
        self.randomize = randomize

    # ------------------------------------------------------------------
    # BatchStrategy interface
    # ------------------------------------------------------------------

    def create_batches(self, commits: list[git.Commit]) -> list[list[git.Commit]]:
        batches: list[list[git.Commit]] = []
        runs_per_commit = self.num_runs * self.num_repeats
        for i in range(0, len(commits), self.batch_size):
            window = commits[i : i + self.batch_size]
            expanded: list[git.Commit] = [c for c in window for _ in range(runs_per_commit)]
            if self.randomize:
                random.shuffle(expanded)
            batches.append(expanded)
        return batches

    def refine_commits(
        self,
        full_commits: list[git.Commit],
        measured_results: list[tuple[git.Commit, float | None]],
        *,
        build_blacklist: set[str],
    ) -> list[list[git.Commit]]:
        return []  # naive strategy never refines


###############################################################################
# Three‑point bisection strategy                                        #####
###############################################################################


class ThreePointBatchStrategy(BatchStrategy):
    """Breadth‑first *3‑point* search using Welch’s t‑test for regressions."""

    def __init__(self, *, num_runs: int, num_repeats: int) -> None:
        self.num_runs = num_runs
        self.num_repeats = num_repeats

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _nearest_compilable(
        commits: list[git.Commit], idx: int, *, blacklist: set[str], available: set[str]
    ) -> git.Commit | None:
        """Return the *nearest* commit (left‑then‑right) that built successfully."""
        # search to the left, then to the right
        for offset in range(1, max(idx, len(commits) - idx)):
            for pos in (idx - offset, idx + offset):
                if 0 <= pos < len(commits):
                    sha = commits[pos].hexsha
                    if sha not in blacklist and sha in available:
                        return commits[pos]
        return None

    # ------------------------------------------------------------------
    # BatchStrategy interface
    # ------------------------------------------------------------------

    def create_batches(self, commits: list[git.Commit]) -> list[list[git.Commit]]:  # noqa: D401
        n = len(commits)
        if n == 0:
            return []
        if n < 3:
            return [[c for c in commits for _ in range(self.num_runs * self.num_repeats)]]

        first, mid, last = commits[0], commits[n // 2], commits[-1]
        replicated: list[git.Commit] = []
        for c in (first, mid, last):
            replicated.extend([c] * self.num_runs * self.num_repeats)
        return [replicated]

    # pylint: disable=too-complex
    def refine_commits(
        self,
        full_commits: list[git.Commit],
        measured_results: list[tuple[git.Commit, float | None]],
        *,
        build_blacklist: set[str],
    ) -> list[list[git.Commit]]:
        """Determine next regions to inspect – may request *re‑sampling*.

        The algorithm handles *three* scenarios:

        1. **Build failure** – if a pivot failed to compile, we choose the
           nearest compilable neighbour.
        2. **Non‑normal data** – if the baseline *or* a pivot fails the
           D’Agostino test (\*p* < 0.05), we request *the same region* again so
           that additional samples accumulate.
        3. **Significant regression** – standard Welch’s *t* detects a shift;
           slice between baseline and pivot is queued.
        """
        if len(full_commits) < 3:
            return []

        # 1) Bucket energy values per commit SHA
        values: dict[str, list[float]] = {}
        for commit, maybe_val in measured_results:
            if maybe_val is None:
                continue
            values.setdefault(commit.hexsha, []).append(maybe_val)

        baseline_sha = full_commits[0].hexsha
        pivot_candidates = [full_commits[len(full_commits) // 2], full_commits[-1]]

        next_regions: list[list[git.Commit]] = []
        for pivot in pivot_candidates:
            base_vals = values.get(baseline_sha, [])
            cand_sha = pivot.hexsha
            cand_vals = values.get(cand_sha, [])

            # 1a) Substitute neighbour if pivot could not be built
            if cand_sha not in values:
                replacement = self._nearest_compilable(
                    full_commits, full_commits.index(pivot), blacklist=build_blacklist, available=set(values)
                )
                if replacement is None:
                    continue  # completely stuck
                cand_sha = replacement.hexsha
                cand_vals = values[cand_sha]
                pivot = replacement  # type: ignore[assignment]

            # Need at least 3 values each to run stats; otherwise re‑sample region
            if len(base_vals) < 3 or len(cand_vals) < 3:
                next_regions.append(full_commits)
                continue

            # 2) Normality – if either fails, re‑sample
            if normaltest(base_vals).pvalue < 0.05 or normaltest(cand_vals).pvalue < 0.05:
                next_regions.append(full_commits)
                continue

            # 3) Welch’s t‑test for mean shift
            if ttest_ind(base_vals, cand_vals, equal_var=False).pvalue < 0.05:
                i0, i1 = sorted((0, full_commits.index(pivot)))
                region = full_commits[i0 : i1 + 1]
                next_regions.append(region)

        return next_regions


###############################################################################
# Pipeline orchestration                                                #####
###############################################################################


def _build_context(commit: git.Commit, repo_path: Path) -> Context:
    """Factory for a fresh :class:`Context`."""
    return Context(commit=commit.hexsha, repo_path=repo_path)


class Pipeline:  # pylint: disable=too-many-instance-attributes
    """Drive all stages across all commits according to a *strategy*."""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, repo_path: Path | str) -> None:  # noqa: D401
        self.repo_path = Path(repo_path)
        self.config: PipelineConfig = Config.get_config()

        # ------------------------------------------------------------------
        # Stage graph
        # ------------------------------------------------------------------
        plan = self.config.execution_plan
        par = set(getattr(plan, "parallel_stages", []))

        self.pre_stage = ContainerStage(
            "pre",
            [VerifyPerfStage(), FilterAndRegressionStage()],
            parallel="pre" in par,
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
            parallel="test" in par,
        )
        self.post_stage = ContainerStage("post", [PostTestStage()], parallel="post" in par)

        # ------------------------------------------------------------------
        # Batch strategy
        # ------------------------------------------------------------------
        if getattr(plan, "search_strategy", "naive") == "three_point":
            self.strategy: BatchStrategy = ThreePointBatchStrategy(num_runs=plan.num_runs, num_repeats=plan.num_repeats)
        else:
            self.strategy = NaiveBatchStrategy(
                batch_size=plan.batch_size,
                num_runs=plan.num_runs,
                num_repeats=plan.num_repeats,
                randomize=plan.randomize_tasks,
            )

        # Build‑failure blacklist shared across the entire run
        self._build_blacklist: set[str] = set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_stage_over_contexts(
        self,
        stage: ContainerStage,
        contexts: list[Context],
        progress: Progress,
    ) -> None:
        """Run *stage* over all *contexts*, optionally in parallel."""
        if stage.deduplicate:
            unique: dict[str, Context] = {}
            for ctx in contexts:
                sha = ctx.commit if isinstance(ctx.commit, str) else ctx.commit.hexsha
                unique.setdefault(sha, ctx)
            contexts = list(unique.values())

        total = len(contexts)
        max_workers = getattr(self.config.execution_plan, "max_workers", os.cpu_count() or 1)
        if not max_workers or max_workers < 1:
            max_workers = os.cpu_count() or 1
        task_id = progress.add_task(stage.name, total=total)

        # Parallel execution
        if stage.parallel and total > 1:
            logger.debug("Running stage %s in parallel with %d workers", stage.name, max_workers)
            with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                # modify contexts to include the "worker_process": True
                for ctx in contexts:
                    ctx["worker_process"] = True
                futures = {executor.submit(stage.run, ctx): ctx for ctx in contexts}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        ctx = future.result()
                    except PipelineAbort:
                        executor.shutdown(wait=False, cancel_futures=True)
                        raise
                    except Exception as e:
                        logger.error("Error in stage %s: %s", stage.name, e)
                    finally:
                        progress.update(task_id, advance=1)
        else:
            # Sequential fallback
            for ctx in contexts:
                try:
                    stage.run(ctx)
                except PipelineAbort:
                    raise
                progress.update(task_id, advance=1)

    # ------------------------------------------------------------------
    # Public driver
    # ------------------------------------------------------------------

    def run(self, *, initial_commits: list[git.Commit] | None = None) -> None:  # noqa: D401
        """Entry‑point executed by :func:`measure`."""
        commits = initial_commits or gather_commits(git.Repo(self.repo_path))

        # ----------------------------------------------
        # Pre‑processing (may drop commits)
        # ----------------------------------------------
        # initialize full context, including filtered commits list
        ctx_full = Context(commit=commits[0], repo_path=self.repo_path, commits=commits)
        self.pre_stage.run(ctx_full)
        if ctx_full.abort_pipeline:
            logger.error("Aborted during *pre* stage – bailing out.")
            return
        # FilterAndRegressionStage may have modified ctx_full.commits
        commits = list(ctx_full.commits or commits)
        logger.info("%d commits remain after filters", len(commits))

        # ----------------------------------------------
        # BFS over regression regions
        # ----------------------------------------------
        queue: list[list[git.Commit]] = [commits]

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
            task_root = progress.add_task("batches", total=0)

            while queue:
                region = queue.pop(0)
                # create batches according to strategy
                batches = self.strategy.create_batches(region)
                progress.reset(task_root, total=len(batches))

                for batch in batches:
                    # build contexts skipping build‑failed commits
                    contexts: list[Context] = [
                        _build_context(c, self.repo_path) for c in batch if c.hexsha not in self._build_blacklist
                    ]
                    if not contexts:
                        continue

                    # 1) Setup (may mark build_failed)
                    try:
                        self._run_stage_over_contexts(self.setup_stage, contexts, progress)
                    except PipelineAbort:
                        return

                    # purge build‑failed before *test* + *post*
                    good_contexts = [c for c in contexts if not c.build_failed]

                    # 5) Flush per-context logs to main logger
                    for ctx in good_contexts:
                        log_context_buffer(ctx)
                    self._build_blacklist.update([
                        (c.commit if isinstance(c.commit, str) else c.commit.hexsha) for c in contexts if c.build_failed
                    ])
                    if not good_contexts:
                        continue

                    # 2) Test + Post
                    try:
                        self._run_stage_over_contexts(self.test_stage, good_contexts, progress)
                        self._run_stage_over_contexts(self.post_stage, good_contexts, progress)
                    except PipelineAbort:
                        return

                    # 3) Gather measurement tuples (may include *None*)
                    results: list[tuple[git.Commit, float | None]] = [
                        (
                            c.commit if isinstance(c.commit, git.Commit) else git.Repo(self.repo_path).commit(c.commit),
                            c.energy_value,
                        )
                        for c in good_contexts
                    ]

                    # 4) Ask strategy for next sub‑regions
                    new_regions = self.strategy.refine_commits(
                        region,
                        results,
                        build_blacklist=self._build_blacklist,
                    )
                    queue.extend(new_regions)

                    progress.update(task_root, advance=1)

        logger.info("Pipeline finished – % d commits black‑listed as unbuildable.", len(self._build_blacklist))


###############################################################################


def log_context_buffer(context: Context) -> None:
    """Flushes buffered log calls from a context to the main logger.

    Reads buffered entries under 'log_buffer' and replays each with original args.
    """
    buffer = getattr(context, "log_buffer", []) or []
    commit_id = context.commit.hexsha[:8] if isinstance(context.commit, git.Commit) else str(context.commit)[:8]
    if not buffer:
        return
    logger.info("----- Logs for commit %s -----", commit_id)
    for level, msg, args, kwargs in buffer:
        logger.log(level, msg, *args, **kwargs)
    logger.info("----- End of logs for %s -----", commit_id)


# Public helper


def measure(config_path: str | Path) -> None:  # noqa: D401
    """High‑level wrapper used by the CLI entry‑point.

    Parameters
    ----------
    config_path
        Path to the *TOML* pipeline configuration file.
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

    pipeline = Pipeline(repo_path)
    try:
        pipeline.run()
    finally:
        # Always attempt cleanup so that repeated runs start fresh
        try:
            repo.git.checkout(config.repo.branch)
        except git.exc.GitError as exc:  # pragma: no cover – non‑fatal
            logger.warning("Could not checkout default branch for cleanup: %s", exc)
        shutil.rmtree(repo_path.parent, ignore_errors=True)


###############################################################################
# End of file                                                            #####
###############################################################################
