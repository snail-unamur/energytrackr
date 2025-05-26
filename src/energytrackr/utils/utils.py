"""Utility functions."""

import math
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from energytrackr.config.config_store import Config
from energytrackr.pipeline.context import Context
from energytrackr.utils.logger import logger


def run_command(
    arg: str,
    cwd: str | None = None,
    context: Context | None = None,
) -> subprocess.CompletedProcess[str]:
    """Executes a shell command, streaming and capturing its output in real time.

    Args:
        arg (str): The command to run.
        cwd (str | None): The working directory for the command.
        context (Context | None): The context for logging.

    Returns:
        subprocess.CompletedProcess[str]: The completed process object containing the command's output and return code.

    """
    logger.info("Running command: %s", arg, context=context)
    with subprocess.Popen(
        arg,
        cwd=cwd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,  # Ensures stdout and stderr are returned as strings
    ) as process:
        config = Config.get_config()
        stdout, stderr = process.communicate(timeout=config.timeout)
        retcode = process.returncode

    if retcode:
        logger.error("Command failed with return code %d", retcode, context=context)
        logger.error("stdout: %s", stdout, context=context)
        logger.error("stderr: %s", stderr, context=context)

    return subprocess.CompletedProcess(
        args=arg,
        returncode=retcode,
        stdout=stdout,
        stderr=stderr,
    )


def nice_number(x: float) -> float:
    """Rounds a given number to a "nice" number, which is a value that is easy to interpret.

    The function determines the order of magnitude of the input number and
    selects a "nice" fraction based on predefined thresholds.

    Args:
        x (float): The input number to be rounded.

    Returns:
        float: A "nice" number that is close to the input value.
    """
    if not x:
        return 0
    thresholds = [1.5, 3, 7]
    exponent = math.floor(math.log10(x))
    fraction = x / (10**exponent)
    if fraction < thresholds[0]:
        nice_fraction = 1
    elif fraction < thresholds[1]:
        nice_fraction = 2
    elif fraction < thresholds[2]:
        nice_fraction = 5
    else:
        nice_fraction = 10
    return nice_fraction * (10**exponent)


def get_local_env(env: Environment, template_path: str) -> Environment:
    """Returns a Jinja2 Environment instance configured for the directory containing the specified template.

    If the provided environment's loader is already set to the template's parent directory, it is returned as-is.
    Otherwise, a new Environment is created with a FileSystemLoader pointing to the template's parent directory.

    Args:
        env (Environment): The current Jinja2 Environment instance.
        template_path (str): The file path to the template.

    Returns:
        Environment: A Jinja2 Environment configured for the template's directory.
    """
    return (
        env
        if Path(template_path).parent == Path(env.loader.searchpath[0])  # type: ignore[attr-defined]
        else Environment(loader=FileSystemLoader(Path(template_path).parent), autoescape=select_autoescape())
    )
