"""Module to filter commits and add regression context based on configuration.

This merged stage first applies filtering criteria to the commit list,
then uses the original commit order along with the configuration parameters
(min_commits_before and min_commits_after) to ensure that each candidate commit
has a previous and/or a next commit for comparison. If a neighboring commit was removed
during filtering, it is added back from the original list.
"""

from git.objects.commit import Commit

from energytrackr.config.config_model import PipelineConfig
from energytrackr.config.config_store import Config
from energytrackr.pipeline.context import Context
from energytrackr.pipeline.stage_interface import PipelineStage
from energytrackr.utils.logger import logger


class FilterAndRegressionStage(PipelineStage):
    """Stage to filter commits and augment them with regression context.

    Combined stage to filter commits and augment them with regression context
    based on the commit order and configuration parameters.
    """

    def run(self, context: Context) -> None:
        """Executes the filter and regression augmentation stage of the pipeline.

        This method processes the list of commits provided in the context, applying filtering criteria
        and augmenting the list for regression detection. It updates the context in place with the
        filtered and augmented list of commits, and may set the 'abort_pipeline' flag in the context
        if no commits remain after filtering.

        Args:
            context (Context): The pipeline context containing at least a "commits" key with a list of Commit objects.

        Side Effects:
            - Logs information and warnings about the commit processing steps.
            - Modifies the "commits" list in the context in place.
            - Sets "abort_pipeline" in the context to True if no commits are available for further processing.
        """
        if not (original_commits := context.get_commits()):
            logger.warning("No commits to process.", context=context)
            context["abort_pipeline"] = True
            return

        config: PipelineConfig = Config.get_config()
        regression_config = config.regression_detection
        min_parents: int = regression_config.min_commits_before
        min_children: int = regression_config.min_commits_after

        commit_index: dict[str, int] = {commit.hexsha: i for i, commit in enumerate(original_commits)}
        original_count: int = len(original_commits)

        self._log_commit_counts("before filtering", original_count, context)

        filtered_commits: list[Commit] = self._filter_commits(original_commits, config)
        self._log_commit_counts("after filtering", len(filtered_commits), context)
        logger.info("Unique commits after filtering: %d", len({c.hexsha for c in filtered_commits}), context=context)

        if not filtered_commits:
            logger.warning("No commits passed the filter criteria.", context=context)
            context["abort_pipeline"] = True
            context["commits"].clear()
            return

        logger.info("%d commits passed the filter criteria.", len(filtered_commits), context=context)

        final_commits: list[Commit] = self._augment_commits(
            filtered_commits,
            original_commits,
            commit_index,
            min_parents,
            min_children,
        )

        self._log_commit_counts("after regression augmentation", len(final_commits), context)
        if len(final_commits) > original_count:
            logger.warning(
                "Final commit count (%d) exceeds original commit count (%d)!",
                len(final_commits),
                original_count,
                context=context,
            )

        # Modify the list in place
        commits_ref: list[Commit] = context["commits"]
        commits_ref.clear()
        commits_ref.extend(final_commits)

    @staticmethod
    def _filter_commits(commits: list[Commit], config: PipelineConfig) -> list[Commit]:
        filtered: list[Commit] = []
        for commit in commits:
            remove_commit: bool = False
            has_tracked_file: bool = False
            for file in commit.stats.files:
                if any(str(file).startswith(directory) for directory in config.ignored_directories):
                    remove_commit = True
                    break
                if str(file).endswith(tuple(config.tracked_file_extensions)):
                    has_tracked_file = True
            if not remove_commit and has_tracked_file:
                filtered.append(commit)
        return filtered

    @staticmethod
    def _augment_commits(
        filtered_commits: list[Commit],
        original_commits: list[Commit],
        commit_index: dict[str, int],
        min_parents: int,
        min_children: int,
    ) -> list[Commit]:
        original_count: int = len(original_commits)
        augmented: dict[Commit, Commit] = {commit: commit for commit in filtered_commits}
        for commit in filtered_commits:
            if not (hexsha := commit.hexsha):
                logger.warning("Commit %s has no hexsha.", commit, context={})
                continue
            if (pos := commit_index.get(hexsha)) is None:
                logger.warning("Commit %s not found in commit_index.", hexsha, context={})
                continue
            for i in range(1, min_parents + 1):
                if (neighbor_pos := pos - i) < 0:
                    break
                neighbor: Commit = original_commits[neighbor_pos]
                if neighbor.hexsha not in augmented:
                    augmented[neighbor] = neighbor
            for i in range(1, min_children + 1):
                if (neighbor_pos := pos + i) >= original_count:
                    break
                neighbor = original_commits[neighbor_pos]
                if neighbor.hexsha not in augmented:
                    augmented[neighbor] = neighbor
        final_commits: list[Commit] = [augmented[h] for h in augmented]
        final_commits.sort(key=lambda c: commit_index[c.hexsha])
        return final_commits

    @staticmethod
    def _log_commit_counts(stage: str, count: int, context: Context) -> None:
        logger.info("Number of commits %s: %d", stage, count, context=context)
