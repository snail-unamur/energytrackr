"""Tests for the TemperatureCheckStage class."""

import logging
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from energytrackr.config.config_store import Config
from energytrackr.pipeline.core_stages.temperature_check_stage import TemperatureCheckStage
from energytrackr.utils.logger import logger
from energytrackr.utils.utils import read_cpu_temp


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Prevent real sleeping in tests, but record calls.

    Args:
        monkeypatch (pytest.MonkeyPatch): The pytest monkeypatch fixture.

    Returns:
        list[Any]: A list to record sleep calls.
    """
    calls = []
    monkeypatch.setattr(time, "sleep", calls.append)
    return calls


@pytest.fixture
def dummy_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, SimpleNamespace]:
    """Stub Config.get_config() to return cpu_thermal_file & safe_limit.

    Args:
        tmp_path (Path): The temporary path fixture.
        monkeypatch (pytest.MonkeyPatch): The pytest monkeypatch fixture.

    Returns:
        tuple[Any, SimpleNamespace]: A tuple containing a fake file and a configuration object.
    """
    fake_file = tmp_path / "dummy_temp"
    fake_file.write_text("0")
    limits = SimpleNamespace(temperature_safe_limit=6000)
    cfg = SimpleNamespace(cpu_thermal_file=str(fake_file), limits=limits)
    monkeypatch.setattr(Config, "get_config", classmethod(lambda _: cfg))
    return fake_file, cfg


def test_read_cpu_temp_success(tmp_path: Path) -> None:
    """Test that the function reads the CPU temperature correctly.

    Args:
        tmp_path (Path): The temporary path fixture.
    """
    temperature = 42000
    f = tmp_path / "t"
    f.write_text(f" {temperature}\n")
    assert read_cpu_temp(str(f)) == temperature


def test_read_cpu_temp_file_not_found() -> None:
    """Test that the function raises an OSError if the file does not exist."""
    missing = "/nonexistent/path"
    with pytest.raises(OSError):
        read_cpu_temp(missing)


def test_read_cpu_temp_invalid_content(tmp_path: Path) -> None:
    """Test that the function raises a ValueError if the content is not an integer.

    Args:
        tmp_path (Path): The temporary path fixture.
    """
    f = tmp_path / "t"
    f.write_text("not-an-int")
    with pytest.raises(ValueError):
        read_cpu_temp(str(f))


def test_run_immediate_under_limit(
    dummy_config: tuple[Any, SimpleNamespace],
    caplog: pytest.LogCaptureFixture,
    no_sleep: list[int],
) -> None:
    """Test that the stage exits immediately if the CPU is under the limit.

    Args:
        dummy_config (tuple[Any, SimpleNamespace]): The dummy configuration.
        caplog (pytest.LogCaptureFixture): The pytest log capture fixture.
        no_sleep (list[int]): The list to record sleep calls.
    """
    fake_file, _ = dummy_config
    fake_file.write_text("5000")

    # Raise this module's logger to INFO
    caplog.set_level(logging.INFO, logger=logger.name)

    stage = TemperatureCheckStage()
    stage.run(context={})

    # now caplog.records will include our INFO call
    assert any(
        rec.levelno == logging.INFO and "CPU temperature: 5000 (limit: 6000)" in rec.getMessage() for rec in caplog.records
    )
    assert no_sleep == []


def test_run_two_reads_above_then_below(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    no_sleep: list[Any],
    dummy_config: tuple[Any, SimpleNamespace],
) -> None:
    """Test that the stage waits if the CPU is above the limit, then exits when below.

    Args:
        monkeypatch (pytest.MonkeyPatch): The pytest monkeypatch fixture.
        caplog (pytest.LogCaptureFixture): The pytest log capture fixture.
        no_sleep (list[Any]): The list to record sleep calls.
        dummy_config (tuple[Any, SimpleNamespace]): The dummy configuration.
    """
    _, _ = dummy_config
    seq = [7000, 5000]
    monkeypatch.setattr(
        "energytrackr.pipeline.core_stages.temperature_check_stage.read_cpu_temp",
        lambda _: seq.pop(0),
    )

    caplog.set_level(logging.WARNING, logger=logger.name)

    stage = TemperatureCheckStage()
    stage.run(context={})

    assert any(
        rec.levelno == logging.WARNING and "CPU too hot (7000), waiting..." in rec.getMessage() for rec in caplog.records
    )
    assert no_sleep == [2]


@pytest.mark.parametrize("exc", [OSError("fail"), ValueError("bad")])
def test_run_read_error_breaks(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    exc: OSError | ValueError,
    no_sleep: list[int],
    dummy_config: tuple[Any, SimpleNamespace],  # noqa: ARG001
) -> None:
    """Test that a read error breaks the loop and logs a warning.

    Args:
        monkeypatch (pytest.MonkeyPatch): The pytest monkeypatch fixture.
        caplog (pytest.LogCaptureFixture): The pytest log capture fixture.
        exc (OSError | ValueError): The exception to raise during the test.
        no_sleep (list[int]): The list to record sleep calls.
    """
    monkeypatch.setattr(
        "energytrackr.pipeline.core_stages.temperature_check_stage.read_cpu_temp",
        staticmethod(lambda _: (_ for _ in ()).throw(exc)),
    )

    caplog.set_level(logging.WARNING, logger=logger.name)

    stage = TemperatureCheckStage()
    stage.run(context={})

    assert any(
        rec.levelno == logging.WARNING and "Could not read or parse temperature" in rec.getMessage() for rec in caplog.records
    )
    assert no_sleep == []
