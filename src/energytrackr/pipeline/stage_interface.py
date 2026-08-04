"""Interface for pipeline stages."""

from __future__ import annotations

import concurrent.futures as _cf
import os
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import fields
from typing import ClassVar

import git
from rich.progress import (
    Progress,
    TaskID,
)

from energytrackr.pipeline.context import Context
from energytrackr.utils.exceptions import PipelineAbortError
from energytrackr.utils.logger import logger


class PipelineStage(ABC):
    """Abstract base for pipeline stages.

    Each stage receives a shared 'context' dict and can read/write data.
    """

    @abstractmethod
    def run(self, context: Context) -> None:
        """Execute the logic for this stage, possibly modifying context.

        If the stage fails critically, set context["abort_pipeline"] = True.

        Args:
            context (Context): Shared context for the pipeline.
        """


def _run_stage_in_worker(stage_class: type[PipelineStage], stage_args: tuple, stage_kwargs: dict, ctx: Context) -> Context:
    """Helper function to execute a pipeline stage in a worker process or thread.

    Instantiates the given stage class with provided arguments and runs it
    on the supplied context. Returns the modified context.

    Args:
        stage_class (type[PipelineStage]): The class of the pipeline stage to instantiate.
        stage_args (tuple): Positional arguments for the stage constructor.
        stage_kwargs (dict): Keyword arguments for the stage constructor.
        ctx (Context): The context object to process.

    Returns:
        Context: The modified context after stage execution.
    """
    stage = stage_class(*stage_args, **stage_kwargs)
    stage.run(ctx)
    return ctx


class StageGroup(PipelineStage):
    """Composite stage that runs an ordered list of *sub-stages*.

    Parameters
    ----------
    name
        Human-readable identifier (appears in logs and progress bars).
    stages
        Ordered collection of concrete :class:`PipelineStage` objects.
    parallel
        If *True* and more than one *context* is supplied, execute in a
        :pyclass:`concurrent.futures.ProcessPoolExecutor`.
    deduplicate
        If *True*, ensure each *unique* commit SHA only executes once - useful
        to avoid rebuilding the same revision across measurement repeats.
    """

    name: str
    _stages: Sequence[PipelineStage]
    _parallel: bool = False
    _deduplicate: bool = False

    #: Max workers cache (minor optimisation so we only query this once)
    _MAX_WORKERS: ClassVar[int | None] = None

    def __init__(
        self,
        name: str,
        stages: Sequence[PipelineStage],
        *,
        parallel: bool = False,
        deduplicate: bool = False,
    ) -> None:
        """Create a new stage group."""
        self.name = name
        self._stages = list(stages)
        self._parallel = parallel
        self._deduplicate = deduplicate

    def run(self, context: Context) -> None:
        """Run *all* sub-stages *sequentially* on the supplied context.

        Args:
            context: The context object to process.

        Raises:
            PipelineAbortError: If any stage sets *context.abort_pipeline* to *True*.
        """
        logger.debug("[%s] start", self.name, extra={"context": context})
        for stage in self._stages:
            stage.run(context)
            if context.abort_pipeline:
                logger.error("[%s] abort requested by %s", self.name, stage.__class__.__name__)
                raise PipelineAbortError from None
        logger.debug("[%s] done", self.name, extra={"context": context})

    def execute_over(self, contexts: list[Context], progress: Progress, task_id: TaskID) -> None:
        """Execute this StageGroup for every context in *contexts*.

        The method delegates deduplication and optional parallel
        execution, updating the supplied *rich* progress bar.

        Args:
            contexts: List of contexts to process.
            progress: Progress bar instance to update.

        Raises:
            PipelineAbortError: If any stage sets *context.abort_pipeline* to *True*.
        """
        if self._deduplicate:
            seen: dict[str, Context] = {}
            for ctx in contexts:
                sha = ctx.commit if isinstance(ctx.commit, str) else ctx.commit.hexsha
                seen.setdefault(sha, ctx)
            contexts = list(seen.values())

        if not (total := len(contexts)):
            return

        # task_id = progress.add_task(self.name, total=total)

        # Decide worker count lazily & memoise
        if StageGroup._MAX_WORKERS is None:
            StageGroup._MAX_WORKERS = max(1, (os.cpu_count() or 1))
        max_workers = StageGroup._MAX_WORKERS

        if self._parallel and total > 1:
            logger.debug("Running stage %s in parallel with %d workers", self.name, max_workers)
            with _cf.ProcessPoolExecutor(max_workers=max_workers) as executor:
                # annotate contexts so logs buffer inside worker
                for ctx in contexts:
                    ctx["worker_process"] = True

                stage_class = type(self)
                stage_args = (self.name, self._stages)
                stage_kwargs = {"parallel": self._parallel, "deduplicate": self._deduplicate}
                futures = {
                    executor.submit(_run_stage_in_worker, stage_class, stage_args, stage_kwargs, ctx): ctx for ctx in contexts
                }

                for future in _cf.as_completed(futures):
                    orig_ctx = futures[future]
                    new_ctx: Context | None = None
                    try:
                        new_ctx = future.result()
                    except PipelineAbortError:
                        executor.shutdown(wait=False, cancel_futures=True)
                        raise
                    except Exception as exc:
                        logger.error("Error in stage %s: %s", self.name, exc)
                    else:
                        # Merge fields back into original context
                        for fld in fields(Context):
                            setattr(orig_ctx, fld.name, getattr(new_ctx, fld.name))
                        self.log_context_buffer(orig_ctx)
                    finally:
                        progress.update(task_id, advance=1)
                    if new_ctx and new_ctx.abort_pipeline:
                        logger.error("Stage %s requested abort for commit %s", self.name, new_ctx.commit)
                        contexts.pop(contexts.index(orig_ctx))

        else:
            to_remove = []
            for ctx in contexts:
                ctx["worker_process"] = False
                self.run(ctx)
                if ctx.abort_pipeline:
                    logger.error("Stage %s requested abort for commit %s", self.name, ctx.commit)
                    to_remove.append(ctx)  # Mark for removal after iteration
                progress.update(task_id, advance=1)
            for ctx in to_remove:
                contexts.remove(ctx)

    @staticmethod
    def log_context_buffer(context: Context) -> None:
        """Flush buffered log calls from *context* to the main logger.

        Args:
            context: The context object containing the log buffer.
        """
        buffer = getattr(context, "log_buffer", []) or []
        commit_id = context.commit.hexsha[:8] if isinstance(context.commit, git.Commit) else str(context.commit)[:8]
        if not buffer:
            return
        logger.info("----- Logs for commit %s -----", commit_id)
        for level, msg, args, kwargs in buffer:
            logger.log(level, msg, *args, **kwargs)
        logger.info("----- End of logs for %s -----", commit_id)
