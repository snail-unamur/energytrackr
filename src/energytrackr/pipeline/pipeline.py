"""Pipeline orchestrator for running stages on commits in a repository."""

import concurrent.futures
import os
import random
import shutil
import sys
from typing import Any

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
from energytrackr.pipeline.custom_stages.java_setup_stage import JavaSetupStage
from energytrackr.pipeline.stage_interface import PipelineStage
from energytrackr.utils.git_utils import clone_or_open_repo, gather_commits
from energytrackr.utils.logger import logger

pre_stages: list[PipelineStage] = [
    VerifyPerfStage(),
    FilterAndRegressionStage(),
]

pre_test_stages: list[PipelineStage] = [
    CopyDirectoryStage(),
    SetDirectoryStage(),
    CheckoutStage(),
    JavaSetupStage(),
    BuildStage(),
]

batch_stages: list[PipelineStage] = [
    TemperatureCheckStage(),
    SetDirectoryStage(),
    # JavaSetupStage(),
    MeasureEnergyStage(),
    PostTestStage(),
]


def compile_stages() -> dict[str, list[PipelineStage]]:
    """Compile the pipeline stages based on the execution plan.

    Returns:
        list[PipelineStage]: The compiled list of pipeline stages.
    """
    return {"pre_stages": pre_stages, "pre_test_stages": pre_test_stages, "batch_stages": batch_stages}


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


def run_setup_commands(commands: list[str]) -> None:
    """Run system-level setup commands if provided.

    Args:
        commands (list[str]): List of shell commands to run.
    """
    for cmd in commands:
        logger.info("Running setup command: %s", cmd)
        os.system(cmd)


def run_pre_stages(commits: list[git.Commit], repo_path: str) -> bool:
    """Run pre-stages on the full commit list. Returns True if pipeline should continue.

    Args:
        commits (list[git.Commit]): List of git.Commit objects to process.
        repo_path (str): Path to the repository.

    Returns:
        bool: True if the pipeline should continue, False if it should abort.
    """
    pre_context = {
        "build_failed": False,
        "abort_pipeline": False,
        "repo_path": repo_path,
        "commits": commits,
    }
    for stage in pre_stages:
        stage.run(pre_context)
        if pre_context.get("abort_pipeline"):
            logger.warning("Pre-stages aborted the pipeline.")
            return False
    return True


def create_batches(
    commits: list[git.Commit],
    batch_size: int,
    num_runs: int,
    num_repeats: int,
    randomize_tasks: bool,
) -> list[list[Any]]:
    """Divide commits into batches and expand according to runs/repeats.

    Args:
        commits (list[Commit]): List of git.Commit objects to process.
        batch_size (int): Number of commits per batch.
        num_runs (int): Number of runs per commit.
        num_repeats (int): Number of repeats for each run.
        randomize_tasks (bool): Whether to randomize the order of tasks in each batch.

    Returns:
        list[list[Any]]: List of batches, where each batch is a list of commits.
    """
    commit_batches = [commits[i : i + batch_size] for i in range(0, len(commits), batch_size)]
    batches: list[list[git.Commit]] = []
    for commit_batch in commit_batches:
        batch_tasks: list[git.Commit] = []
        runs_per_commit = num_runs * num_repeats
        for commit in commit_batch:
            batch_tasks.extend([commit] * runs_per_commit)
        if randomize_tasks:
            random.shuffle(batch_tasks)
        batches.append(batch_tasks)
    return batches


def restore_head(repo: git.Repo, branch: str) -> None:
    """Restore the repository's HEAD to the latest commit on the specified branch.

    Args:
        repo (git.Repo): The Git repository object.
        branch (str): The branch to restore HEAD to.
    """
    repo.git.checkout(branch)
    logger.info("Restored HEAD to latest commit on branch %s.", branch)


def measure(config_path: str) -> None:
    """Executes the measurement process for a given repository based on the provided configuration.

    This function performs the following steps:
    1. Loads the pipeline configuration from the specified path.
    2. Sets up the repository directory and clones or opens the repository.
    3. Optionally runs system-level setup commands.
    4. Collects all commits from the repository.
    5. Runs the pre-stages once on the complete commit list for initial filtering.
    6. Divides the filtered commits into batches.
    7. Executes the remaining pipeline stages on these batches.
    8. Restores the repository's HEAD to the latest commit on the specified branch.

    Args:
        config_path (str): The file path to the configuration file.

    Raises:
        Exceptions raised during the execution of repository operations or pipeline processing.
    """
    load_pipeline_config(config_path)
    # Retrieve the configuration folder
    config_folder = os.path.dirname(config_path)
    config = Config.get_config()

    # Set up directories and repository
    repo_path = setup_project_dirs(config, config_folder)
    repo = clone_or_open_repo(repo_path, config.repo.url, config.repo.clone_options)

    # (Optional) run system-level setup commands.
    if config.setup_commands:
        run_setup_commands(config.setup_commands)

    # Gather all commits from the repository.
    commits = gather_commits(repo)
    logger.info("Collected %d commits to process.", len(commits))

    # Run pre-stages once on the full list of commits
    if not run_pre_stages(commits, repo_path):
        return

    logger.info("Filtered commits: %d", len(commits))

    # Divide the filtered commits into batches
    batches = create_batches(
        commits,
        config.execution_plan.batch_size,
        config.execution_plan.num_runs,
        config.execution_plan.num_repeats,
        config.execution_plan.randomize_tasks,
    )

    pipeline = Pipeline(compile_stages(), repo_path)
    pipeline.run(batches)

    # Restore HEAD
    restore_head(repo, config.repo.branch)


def run_pre_test_stages_for_commit(commit_hexsha: str, repo_path: str) -> dict[str, Any]:
    """Process the pre-test stages for a single commit in a separate process.

    Instead of receiving a git.Commit object (which might not be picklable), we pass the commit's hexsha.
    Each process reopens the repository using repo_path and retrieves the commit object.

    Args:
        commit_hexsha (str): The hexsha of the commit to process.
        repo_path (str): Path to the repository.

    Returns:
        dict: The context after processing the stages.
    """
    commit_context: dict[str, Any] = {
        "commit": commit_hexsha,
        "build_failed": False,
        "abort_pipeline": False,
        "repo_path": repo_path,
        "worker_process": True,
    }

    # 1. Re-open the repository
    try:
        repo = git.Repo(repo_path)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError) as e:
        logger.exception("Invalid repo at %s: %s", repo_path, e, context=commit_context)
        commit_context["abort_pipeline"] = True
        return commit_context
    except Exception as e:
        logger.exception("Unexpected error opening %s: %s", repo_path, e, context=commit_context)
        commit_context["abort_pipeline"] = True
        return commit_context

    # 2. Retrieve the commit object
    try:
        commit = repo.commit(commit_hexsha)
    except (ValueError, git.BadName) as e:
        logger.exception("Bad commit hexsha %s: %s", commit_hexsha, e, context=commit_context)
        commit_context["abort_pipeline"] = True
        return commit_context
    except Exception as e:
        logger.exception("Unexpected error retrieving commit %s: %s", commit_hexsha, e, context=commit_context)
        commit_context["abort_pipeline"] = True
        return commit_context

    # Success: record the resolved hexsha
    commit_context["commit"] = commit.hexsha

    # 3. Execute each pre-test stage in isolation
    for stage in pre_test_stages:
        try:
            stage.run(commit_context)
        except Exception as e:
            logger.exception(
                "Error running stage %s on commit %s: %s",
                stage.__class__.__name__,
                commit.hexsha,
                e,
                context=commit_context,
            )
            # If a stage fails fatally, signal to abort further stages
            commit_context["abort_pipeline"] = True

        if commit_context.get("abort_pipeline"):
            break

    return commit_context


def log_context_buffer(context: dict[str, Any]) -> None:
    """Flushes buffered log calls from a context dict to the main logger.

    Reads the list of buffered entries under `context["log_buffer"]`, and replays
    each one (including its original format string and args).

    Args:
        context: A dict which should contain:
            - "log_buffer": List of tuples (level, msg, args, kwargs)
            - "commit": Optional str commit identifier for header logging
    """
    buffer: list[tuple[int, str, tuple[Any, ...], dict[str, Any]]] = context.get("log_buffer", [])
    commit_id: str = context.get("commit", "UNKNOWN")

    if not buffer:
        return

    logger.info("----- Logs for commit %s -----", commit_id[:8])
    for level, fmt, args, kwargs in buffer:
        logger.log(level, fmt, *args, **kwargs)
    logger.info("----- End of logs for %s -----\n", commit_id[:8])


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


class Pipeline:
    """Orchestrates the provided stages for each commit in sequence."""

    def __init__(self, stages: dict[str, list[PipelineStage]], repo_path: str) -> None:
        """Initializes the Pipeline with the given stages and configuration.

        Args:
            stages (dict[str, list[PipelineStage]]): A dictionary where the keys are stage names (as strings)
                and the values are lists of PipelineStage objects representing the stages of the pipeline.
            repo_path (str): The path to the Git repository to be processed.

        """
        self.stages = stages
        self.config = Config.get_config()
        self.repo_path = repo_path

    @staticmethod
    def _run_stage_group(stages: list[PipelineStage], context: dict[str, Any]) -> bool:
        """Run a group of stages with the given context.

        Args:
            stages (list[PipelineStage]): A list of PipelineStage objects to run.
            context (dict[str, Any]): A dictionary containing the context for the pipeline execution.
                This context is passed to each stage during execution.

        Returns:
            bool: True if all stages completed successfully, False if any stage aborted the pipeline.
        """
        for stage in stages:
            stage.run(context)
            if context.get("abort_pipeline"):
                logger.warning("Aborting remaining stages for stage %s", stage.__class__.__name__)
                return False
        return True

    def run(self, batches: list[list[git.Commit]]) -> None:
        """Executes the pipeline over a list of batches, where each batch contains a list of commits.

        Args:
            batches (list[list[git.Commit]]): A list of batches, where each batch is a list of git.Commit objects.
        """
        failed_commits: set[str] = set()

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
            pipeline_task = progress.add_task("🔋Energy Pipeline", total=len(batches))

            for batch in batches:
                logger.info("Processing batch of %d tasks", len(batch))
                unique_commit_hexshas = list({commit.hexsha for commit in batch})

                self._run_pre_test_stages(unique_commit_hexshas, failed_commits, progress)
                batch_to_process = [commit for commit in batch if commit.hexsha not in failed_commits]
                self._run_batch_stages(batch_to_process, progress)

                clean_cache_dir(self.repo_path)
                progress.advance(pipeline_task)

    def _run_pre_test_stages(
        self,
        unique_commit_hexshas: list[str],
        failed_commits: set[str],
        progress: Progress,
    ) -> None:
        """Run all pre-test stages on each unique commit, optionally in parallel.

        Args:
            unique_commit_hexshas: List of commit SHAs to process.
            failed_commits: A set to which failed SHAs will be added.
            progress: Rich Progress instance for updating a sub-task bar.
        """
        use_mp: bool = getattr(self.config.execution_plan, "use_multiprocessing", False)
        logger.info("Using multiprocessing: %s", use_mp)
        total = len(unique_commit_hexshas)
        subtask = progress.add_task("Pre batch stages", total=total)

        if use_mp:
            # parallel execution
            with concurrent.futures.ProcessPoolExecutor() as executor:
                futures = {
                    executor.submit(run_pre_test_stages_for_commit, sha, self.repo_path): sha for sha in unique_commit_hexshas
                }
                for future in concurrent.futures.as_completed(futures):
                    sha = futures[future]
                    try:
                        ctx = future.result(timeout=self.config.timeout)
                    except Exception:
                        logger.exception("Commit %s generated an exception.", sha)
                        progress.advance(subtask)
                        continue

                    log_context_buffer(ctx)
                    if ctx.get("abort_pipeline"):
                        logger.warning("Aborting pipeline due to commit %s", sha)
                        sys.exit(1)
                    if ctx.get("build_failed"):
                        logger.warning("Build failed for commit %s", sha)
                        failed_commits.add(sha)

                    desc = f"Pre batch stages (failed: {len(failed_commits)})" if failed_commits else "Pre batch stages"
                    progress.update(subtask, advance=1, description=desc)
            progress.remove_task(subtask)

        else:
            # sequential execution
            for sha in unique_commit_hexshas:
                ctx = run_pre_test_stages_for_commit(sha, self.repo_path)
                log_context_buffer(ctx)
                if ctx.get("abort_pipeline"):
                    logger.warning("Aborting pipeline due to commit %s", sha)
                    sys.exit(1)
                if ctx.get("build_failed"):
                    logger.warning("Build failed for commit %s", sha)
                    failed_commits.add(sha)

                desc = f"Pre batch stages (failed: {len(failed_commits)})" if failed_commits else "Pre batch stages"
                progress.update(subtask, advance=1, description=desc)
            progress.remove_task(subtask)

    def _run_batch_stages(self, batch_to_process: list[git.Commit], progress: Progress) -> None:
        batch_stage_task = progress.add_task(
            "[green]🧪Batch stages",
            total=len(batch_to_process),
        )
        failed_tests_commits: set[str] = set()
        logger.info("Starting pipeline over %d commits...", len(batch_to_process))
        for commit in batch_to_process:
            if commit.hexsha in failed_tests_commits:
                logger.warning("Skipping failed commit %s", commit.hexsha)
                continue

            progress.update(
                batch_stage_task,
                description=f"🧪Batch stages ({commit.hexsha[:8]}) (failed: {len(failed_tests_commits)})",
            )
            progress.advance(batch_stage_task)

            commit_context: dict[str, Any] = {
                "commit": commit,
                "build_failed": False,
                "abort_pipeline": False,
                "repo_path": self.repo_path,
            }
            logger.info("==== Processing commit %s ====", commit.hexsha)

            if not self._run_stage_group(self.stages.get("batch_stages", []), commit_context):
                logger.warning("Commit %s failed to process.", commit.hexsha)
                failed_tests_commits.add(commit.hexsha)
                continue

            logger.info("==== Done with commit %s ====\n", commit.hexsha)

        logger.info("Batch stages completed with %d failed commits.", len(failed_tests_commits))
        progress.remove_task(batch_stage_task)
