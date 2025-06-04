"""Main orchestration module for energy consumption data analysis and reporting."""

import webbrowser
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from energytrackr.plot.config import get_settings
from energytrackr.plot.core.context import Context
from energytrackr.plot.core.interfaces import Configurable, PageObj, PlotObj, Transform
from energytrackr.plot.core.loader import load_callable
from energytrackr.utils.exceptions import (
    CantFindFileError,
    MissingEnergyFieldError,
    ModuleDidNotResolveToClassError,
    MustImplementError,
    UnexpectedArgumentError,
)
from energytrackr.utils.logger import logger


def _resolve_csv_path(input_path: str) -> Path:
    csv_path = Path(input_path).expanduser().resolve()
    if not csv_path.is_file():
        raise CantFindFileError(str(csv_path))
    return csv_path


def _locate_config(csv_path: Path, config_path: str | None) -> Path:
    if config_path:
        cfg = Path(config_path).expanduser().resolve()
        if not cfg.is_file():
            raise CantFindFileError(str(cfg))
        return cfg

    candidates = [
        Path.cwd() / "plot.yml",
        csv_path.with_suffix(".yml"),
        csv_path.parent / "plot.yml",
    ]
    for p in candidates:
        if p.is_file():
            return p

    tried = ", ".join(str(p) for p in candidates)
    raise CantFindFileError(tried)


def _build_context(csv_path: Path, git_repo_path: str | None, energy_fields: list[str]) -> Context:
    if not energy_fields:
        raise MissingEnergyFieldError()

    ctx = Context(input_path=str(csv_path), energy_fields=list(energy_fields))
    if git_repo_path:
        ctx.artefacts["git_repo_path"] = git_repo_path
    return ctx


def _apply_transforms(ctx: Context, transforms: Sequence[dict[str, Any]]) -> None:
    """Instantiate and apply a sequence of Transform steps to the context.

    Each entry in `transforms` must be a dict with:
      - "module": import path to a Transform subclass
      - optional "params": dict of keyword-args for its constructor

    If the class subclasses Configurable, we pass `params` through its
    dataclass-validation; otherwise we ignore `params` and call its zero-arg
    constructor.  We then assert it implements `Transform` so that
    `apply(ctx)` is always available.

    Args:
        ctx: The shared Context to be mutated by each transform.
        transforms: A sequence of specs, each with keys "module" (str) and
            optional "params" (dict).

    Raises:
        ModuleDidNotResolveToClassError: If the module path does not resolve to a class.
        UnexpectedArgumentError: If params contain invalid fields for a Configurable.
        MustImplementError: If the loaded class does not implement Transform.
    """
    for spec in transforms:
        module_path = spec["module"]
        cls_obj = load_callable(module_path)
        if not isinstance(cls_obj, type):
            raise ModuleDidNotResolveToClassError(module_path)
        params: dict[str, Any] = spec.get("params", {}) or {}

        logger.info("▶ Transform %s(%s)", module_path, params)
        # Instantiate, choosing the right constructor
        if issubclass(cls_obj, Configurable):
            try:
                inst_candidate = cls_obj(**params)
            except TypeError as e:
                # Let your Configurable mix-in raise UnexpectedArgumentError if needed
                raise UnexpectedArgumentError(list(params), cls_obj.__name__) from e
        else:
            inst_candidate = cls_obj()

        # Narrow to Transform so `apply` is always visible
        if not isinstance(inst_candidate, Transform):
            raise MustImplementError(cls_obj.__name__, Transform)

        inst_candidate.apply(ctx)


def _resolve_plot_objects(ctx: Context, plot_objs: Sequence[dict[str, Any]]) -> None:
    """Instantiate and register PlotObj plug-ins into the context.

    Each spec must be a dict with:
      - "name": identifier under which to store the object in ctx.plot_objects
      - "module": import path to a PlotObj subclass
      - optional "params": kwargs to pass to its constructor

    If the target class subclasses Configurable, its params will be
    validated against its dataclass; otherwise any params are ignored
    and a zero-arg constructor is used.

    Args:
        ctx: The shared Context to which plot objects are added.
        plot_objs: Sequence of specs for plot objects.

    Raises:
        ModuleDidNotResolveToClassError: If the module path does not resolve to a class.
        UnexpectedArgumentError: If params contain invalid fields for a Configurable.
        MustImplementError: If the loaded class does not implement PlotObj.
    """
    for spec in plot_objs:
        module_path = spec["module"]
        cls_obj = load_callable(module_path)
        if not isinstance(cls_obj, type):
            raise ModuleDidNotResolveToClassError(module_path)
        params: dict[str, Any] = spec.get("params", {}) or {}
        logger.info("▶ PlotObj %s(%s)", module_path, params)

        # Instantiate with or without params
        if issubclass(cls_obj, Configurable):
            try:
                inst_candidate = cls_obj(**params)
            except TypeError as e:
                raise UnexpectedArgumentError(list(params), cls_obj.__name__) from e
        else:
            inst_candidate = cls_obj()

        # Ensure it implements the PlotObj protocol
        if not isinstance(inst_candidate, PlotObj):
            raise MustImplementError(cls_obj.__name__, PlotObj)

        ctx.plot_objects[spec["name"]] = inst_candidate


def _render_page_sections(ctx: Context, page_objs: Sequence[dict[str, Any]]) -> str:
    """Instantiate PageObj plug-ins, render each to HTML, and concatenate.

    Each spec must be a dict with:
      - "module": import path to a PageObj subclass
      - optional "params": kwargs to pass to its constructor

    If the target class subclasses Configurable, its params will be
    validated against its dataclass; otherwise any params are ignored
    and a zero-arg constructor is used.

    Args:
        ctx: The shared Context passed to each renderer.
        page_objs: Sequence of specs for page sections.

    Returns:
        A single HTML string comprising all rendered sections.

    Raises:
        ModuleDidNotResolveToClassError: If the module path does not resolve to a class.
        UnexpectedArgumentError: If params contain invalid fields for a Configurable.
        MustImplementError: If the loaded class does not implement PageObj.
    """
    # Prepare Jinja2 environment once
    templates_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(templates_dir))

    sections: list[str] = []
    for spec in page_objs:
        module_path = spec["module"]
        cls_obj = load_callable(module_path)
        if not isinstance(cls_obj, type):
            raise ModuleDidNotResolveToClassError(module_path)
        params: dict[str, Any] = spec.get("params", {}) or {}
        logger.info("▶ PageObj %s(%s)", module_path, params)

        # Instantiate with or without params
        if issubclass(cls_obj, Configurable):
            try:
                inst_candidate = cls_obj(**params)
            except TypeError as e:
                raise UnexpectedArgumentError(list(params), cls_obj.__name__) from e
        else:
            inst_candidate = cls_obj()

        # Ensure it implements the PageObj protocol
        if not isinstance(inst_candidate, PageObj):
            raise MustImplementError(cls_obj.__name__, PageObj)

        # Render and collect the HTML snippet
        sections.append(inst_candidate.render(env, ctx))

    return "\n".join(sections)


def _build_plots(ctx: Context, plot_objs: Sequence[dict[str, Any]]) -> None:
    """Build plot objects and add them to the context.

    Args:
        ctx (Context): The context object containing data and settings.
        plot_objs (Sequence[dict[str, Any]]): List of plot object specifications.
    """
    for _, spec in enumerate(plot_objs):
        cls = load_callable(spec["module"])
        params = spec.get("params", {}) or {}
        logger.info("▶ PlotObj %s(%s)", spec["module"], params)
        obj = cls(**params)
        obj.build(ctx)


def plot(
    input_path: str,
    git_repo_path: str | None = None,
    config_path: str | None = None,
) -> None:
    """Main entry point: orchestrate loading, plotting, and report generation.

    Args:
        input_path (str): Path to the CSV file containing energy data.
        git_repo_path (str | None): Optional path to a Git repository.
        config_path (str | None): Optional path to the configuration file.
    """
    # Resolve paths
    csv_path = _resolve_csv_path(input_path)
    cfg_path = _locate_config(csv_path, config_path)

    # Load settings
    settings = get_settings(str(cfg_path))

    # Prepare context
    ctx = _build_context(
        csv_path,
        git_repo_path,
        list(settings.energytrackr.data.energy_fields),
    )

    # Apply data transforms
    _apply_transforms(ctx, settings.energytrackr.plot.transforms)

    # Resolve plot objects for the context
    _resolve_plot_objects(ctx, settings.energytrackr.plot.objects)

    # Build plots
    _build_plots(ctx, settings.energytrackr.plot.plots)

    # Render HTML report
    html_content = _render_page_sections(ctx, settings.energytrackr.plot.page)

    # Write out report
    output_file = csv_path.with_suffix(".html")
    output_file.write_text(html_content, encoding="utf-8")
    logger.info("✔ Report exported to %s", output_file)

    # Optionally open in browser
    if settings.energytrackr.report.chart.get("open", False):
        webbrowser.open(output_file.as_uri())
