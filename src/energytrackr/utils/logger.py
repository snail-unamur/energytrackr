"""Logger with context support for logging messages in a structured way.

This module provides ContextLogger, a subclass of logging.Logger, which can
buffer log messages (including their formatting arguments) into a context
dictionary instead of emitting them immediately. You can then call
log_context_buffer() to replay those buffered messages with their original
formatting.
"""

import logging
import os
from datetime import datetime
from typing import Any, cast, override

from rich.logging import RichHandler

SAVE_LOGS_TO_FILE: bool = True


class ContextLogger(logging.Logger):
    """Custom logger class that supports logging with additional context.

    ContextLogger extends the standard `logging.Logger` to allow buffering of
    log calls (including format strings and arguments) into a supplied context
    dict under the `"log_buffer"` key. Later, you can flush that buffer with
    `log_context_buffer()`.

    If no context is provided, or if the context does not contain
    `"worker_process": True`, messages are emitted immediately as normal.

    Attributes:
        None (inherits everything from logging.Logger)

    Methods:
        info, debug, warning, error, critical, exception, log:
            Same signature as base Logger, but support an extra `context` kwarg.
    """

    def _log_with_context(
        self,
        level: int,
        msg: str,
        context: dict[str, Any] | None,
        *args: tuple[Any],
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        """Internal helper: either buffer the log or emit it immediately.

        Args:
            level: Numeric log level (e.g., logging.INFO).
            msg: The format string for the log message.
            context: If provided and `context.get("worker_process")` is truthy,
                buffer the call; otherwise emit immediately.
            *args: Positional format args for the message.
            **kwargs: Keyword args for the message.
        """
        if context is not None and context.get("worker_process"):
            context.setdefault("log_buffer", []).append((level, msg, args, kwargs))
        else:
            # Emit immediately
            super().log(level, msg, *args, **kwargs)

    @override
    def info(self, msg: object, *args: Any, **kwargs: Any) -> None:
        """Log a message with severity 'INFO', optionally buffering it.

        Args:
            msg: The log message or format string.
            *args: Arguments for the format string.
            **kwargs: Keyword arguments. May include `context: dict`.
        """
        context = cast(dict[str, Any] | None, kwargs.pop("context", None))
        self._log_with_context(logging.INFO, str(msg), context, *args, **kwargs)

    @override
    def debug(self, msg: object, *args: Any, **kwargs: Any) -> None:
        """Log a message with severity 'DEBUG', optionally buffering it.

        Args:
            msg: The log message or format string.
            *args: Arguments for the format string.
            **kwargs: Keyword arguments. May include `context: dict`.
        """
        context = cast(dict[str, Any] | None, kwargs.pop("context", None))
        self._log_with_context(logging.DEBUG, str(msg), context, *args, **kwargs)

    @override
    def warning(self, msg: object, *args: Any, **kwargs: Any) -> None:
        """Log a message with severity 'WARNING', optionally buffering it.

        Args:
            msg: The log message or format string.
            *args: Arguments for the format string.
            **kwargs: Keyword arguments. May include `context: dict`.
        """
        context = cast(dict[str, Any] | None, kwargs.pop("context", None))
        self._log_with_context(logging.WARNING, str(msg), context, *args, **kwargs)

    @override
    def error(self, msg: object, *args: Any, **kwargs: Any) -> None:
        """Log a message with severity 'ERROR', optionally buffering it.

        Args:
            msg: The log message or format string.
            *args: Arguments for the format string.
            **kwargs: Keyword arguments. May include `context: dict`.
        """
        context = cast(dict[str, Any] | None, kwargs.pop("context", None))
        self._log_with_context(logging.ERROR, str(msg), context, *args, **kwargs)

    @override
    def critical(self, msg: object, *args: Any, **kwargs: Any) -> None:
        """Log a message with severity 'CRITICAL', optionally buffering it.

        Args:
            msg: The log message or format string.
            *args: Arguments for the format string.
            **kwargs: Keyword arguments. May include `context: dict`.
        """
        context = cast(dict[str, Any] | None, kwargs.pop("context", None))
        self._log_with_context(logging.CRITICAL, str(msg), context, *args, **kwargs)

    @override
    def exception(self, msg: object, *args: Any, **kwargs: Any) -> None:
        """Log a message with severity 'ERROR' including exception info.

        Args:
            msg: The log message or format string.
            *args: Arguments for the format string.
            **kwargs: Keyword arguments. May include `context: dict`.
                If `exc_info` isn't provided, it is set to True to include trace.
        """
        context = cast(dict[str, Any] | None, kwargs.pop("context", None))
        kwargs.setdefault("exc_info", True)
        self._log_with_context(logging.ERROR, str(msg), context, *args, **kwargs)

    @override
    def log(self, level: int, msg: object, *args: Any, **kwargs: Any) -> None:
        """Log a message with a specified level, optionally buffering it.

        Args:
            level: Numeric log level.
            msg: The log message or format string.
            *args: Arguments for the format string.
            **kwargs: Keyword arguments. May include `context: dict`.
        """
        context = cast(dict[str, Any] | None, kwargs.pop("context", None))
        self._log_with_context(level, str(msg), context, *args, **kwargs)


# Install our ContextLogger as the default Logger class
logging.setLoggerClass(ContextLogger)

# Create and configure the main application logger
logger = cast(ContextLogger, logging.getLogger("energy-pipeline"))
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    # Pretty console output
    rich_handler = RichHandler(rich_tracebacks=True)
    rich_handler.setLevel(logging.DEBUG)
    logger.addHandler(rich_handler)

    if SAVE_LOGS_TO_FILE:
        LOG_DIR = "logs"
        os.makedirs(LOG_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(LOG_DIR, f"debug_{timestamp}.log")

        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
