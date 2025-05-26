"""Pipeline stage to copy a directory to a target location."""

import shutil
from pathlib import Path

from energytrackr.pipeline.context import Context
from energytrackr.pipeline.stage_interface import PipelineStage
from energytrackr.utils.exceptions import MissingContextKeyError, SourceDirectoryNotFoundError
from energytrackr.utils.logger import logger


class CopyDirectoryStage(PipelineStage):
    """Pipeline stage to copy a directory to a target location."""

    def run(self, context: Context) -> None:  # noqa: PLR6301
        """Executes the logic to copy a directory from source to target.

        Args:
            context (Context): The pipeline context containing at least a "source_dir" key with the path to the source
                               directory and a "target_dir" key with the path to the destination directory.

        Raises:
            MissingContextKeyError: If the required keys are missing in the context.
            SourceDirectoryNotFoundError: If the source directory does not exist.
        """
        if not (repo_path := context.get("repo_path")):
            raise MissingContextKeyError("repo_path")
        source = Path(repo_path).resolve()
        logger.info("Source directory: %s", source, context=context)
        target = Path(f"{context.get('repo_path')}_{context['commit']}").resolve()

        if not source.is_dir():
            raise SourceDirectoryNotFoundError(source)

        logger.info("Copying directory from %s to %s", source, target, context=context)
        try:
            shutil.copytree(src=source, dst=target, dirs_exist_ok=True)
        except Exception as e:
            logger.error("Error copying directory: %s", e, context=context)
            context["abort_pipeline"] = True
            return
        logger.info("Copy completed.", context=context)
