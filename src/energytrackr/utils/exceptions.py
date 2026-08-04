"""Custom exceptions for the application."""

from pathlib import Path

from bokeh.core.validation.check import ValidationIssues


class UnknownCommandError(Exception):
    """Exception raised for unknown commands.

    Attributes:
        command (str): The command that caused the exception.
    """

    def __init__(self, command: str) -> None:
        """Initialize the exception with the unknown command.

        Args:
            command (str): The command that caused the exception.
        """
        super().__init__(f"Unknown command: {command}")


class ConfigurationSingletonAlreadySetError(ValueError):
    """Custom ValueError for errors related to the configuration singleton."""

    def __str__(self) -> str:
        """Returns the custom error message.

        Returns:
            str: The custom error message.
        """
        return "Configuration already initialized."


class ConfigurationSingletonNotSetError(Exception):
    """Custom Exception for errors related to the configuration singleton."""

    def __str__(self) -> str:
        """Returns the custom error message.

        Returns:
            str: The custom error message.
        """
        return "Configuration not initialized."


class SourceDirectoryNotFoundError(Exception):
    """Exception raised when the source directory is not found."""

    def __init__(self, path: Path) -> None:
        """Initialize the exception with a custom message.

        Args:
            path (Path): The path to the source directory that was not found.
        """
        super().__init__(f"Source directory not found: {path.resolve()}")


class TargetDirectoryNotFoundError(Exception):
    """Exception raised when the target directory is not found."""

    def __init__(self, path: Path) -> None:
        """Initialize the exception with a custom message.

        Args:
            path (Path): The path to the target directory that was not found.
        """
        super().__init__(f"Target directory not found: {path.resolve()}")


class MissingContextKeyError(Exception):
    """Exception raised when a required key is missing in the context."""

    def __init__(self, key: str) -> None:
        """Initialize the exception with a custom message.

        Args:
            key (str): The missing key that caused the exception.
        """
        super().__init__(f"Missing required key: {key}")


class CantFindFileError(FileNotFoundError):
    """Exception raised when a file cannot be found.

    Inherits from FileNotFoundError to provide a more specific error message.
    """

    def __init__(self, path: str) -> None:
        """Initialize the exception with a custom message."""
        super().__init__(f"File not found: {path}")


class SettingsReadOnlyError(AttributeError):
    """Exception raised when attempting to modify a read-only Settings object."""

    def __init__(self) -> None:
        """Initialize the exception with a custom message."""
        super().__init__("Settings object is read-only")


class MissingEnergyTrackrKeyError(KeyError):
    """Exception raised when the top-level 'energytrackr' key is missing in the YAML configuration."""

    def __init__(self) -> None:
        """Initialize the exception with a custom message."""
        super().__init__("Top-level 'energytrackr' key missing in YAML.")


class PlotObjectDidNotInitializeFigureError(RuntimeError):
    """Raised when the first PlotObj does not initialize ctx.fig."""

    def __init__(self, module: str) -> None:
        """Initialize the exception with a custom message.

        Args:
            module (str): The module name of the PlotObj that failed to initialize.
        """
        super().__init__(f"First PlotObj '{module}' did not initialize ctx.fig.")


class MissingEnergyFieldError(ValueError):
    """Exception raised when no energy fields are specified in the configuration."""

    def __init__(self) -> None:
        """Initialize the exception with a custom message."""
        super().__init__("Configuration must specify at least one energy field.")


class InvalidDottedPathError(ValueError):
    """Raised when the dotted path is not in the expected 'mod:attr' format."""

    def __init__(self, dotted: str) -> None:
        """Initialize the exception with a custom message.

        Args:
            dotted (str): The invalid dotted path that caused the exception.
        """
        super().__init__(f"Invalid dotted path '{dotted}', expected 'mod:attr'.")


class AttributeNotFoundError(ImportError):
    """Raised when the attribute is not found in the specified module."""

    def __init__(self, mod_path: str, attr: str) -> None:
        """Initialize the exception with a custom message.

        Args:
            mod_path (str): The module path where the attribute was expected to be found.
            attr (str): The attribute that was not found in the module.
        """
        super().__init__(f"Module '{mod_path}' has no attribute '{attr}'.")


class InvalidLegendClickPolicyError(ValueError):
    """Exception raised when an invalid legend click policy is provided."""

    def __init__(self, policy: str, valid: list) -> None:
        """Initialize with the invalid policy and valid options.

        Args:
            policy (str): The invalid policy value.
            valid (list): The list of valid policy values.
        """
        super().__init__(f"Invalid legend-click policy {policy!r}; must be one of {valid}")


class CommitStatsMissingOrEmptyDataFrameError(ValueError):
    """Exception raised when the DataFrame is missing or empty in CommitStats, or the specified column is not found."""

    def __init__(self, column: str) -> None:
        """Initialize the exception with a custom message.

        Args:
            column (str): The column that was expected in the DataFrame.
        """
        super().__init__(f"CommitStats: missing or empty DataFrame for column '{column}'")


class PlotAlreadyRegisteredError(ValueError):
    """Exception raised when a plot class is already registered."""

    def __init__(self, name: str) -> None:
        """Initialize the exception with the plot class name.

        Args:
            name (str): The name of the plot class that is already registered.
        """
        super().__init__(f"Plot '{name}' already registered.")


class PlotLabelsNotSetError(ValueError):
    """Exception raised when plot labels are not set."""

    def __init__(self, plot_key: str) -> None:
        """Initialize the exception with the plot key.

        Args:
            plot_key (str): The key identifying the plot.
        """
        super().__init__(f"{plot_key} plot labels not set.")


class PlotSourcesNotSetError(ValueError):
    """Exception raised when plot sources are not set."""

    def __init__(self, plot_key: str) -> None:
        """Initialize the exception with the plot key.

        Args:
            plot_key (str): The key identifying the plot.
        """
        super().__init__(f"Sources not set for graph {plot_key}")


class NotAPlotObjTypeError(TypeError):
    """Exception raised when an object is not a PlotObj."""

    def __init__(self, name: str) -> None:
        """Initialize the exception with the object name.

        Args:
            name (str): The name of the object that is not a PlotObj.
        """
        super().__init__(f"Plot object '{name}' is not a PlotObj")


class BokehValidationIssuesError(ValueError):
    """Exception raised when Bokeh validation issues are detected in a tab."""

    def __init__(self, tab_title: str, issues: ValidationIssues) -> None:
        """Initialize the exception with the tab title and issues.

        Args:
            tab_title (str): The title of the tab with validation issues.
            issues: The Bokeh validation issues object.
        """
        super().__init__(f"Bokeh validation issues in tab '{tab_title}': {issues}")


class UnexpectedArgumentError(TypeError):
    """Exception raised when MACDLine receives unexpected keyword arguments."""

    def __init__(self, invalid_args: list[str], cls: str) -> None:
        """Initialize with the list of invalid argument names.

        Args:
            invalid_args (list[str]): The unexpected argument names.
            cls (str): The class that raised the error.
        """
        args_str = ", ".join(sorted(invalid_args))
        super().__init__(f"{cls} got unexpected argument(s): {args_str}")


class NotADataclassTypeError(TypeError):
    """Exception raised when a provided class is not a dataclass type."""

    def __init__(self, config_cls: type) -> None:
        """Initialize with the offending class type.

        Args:
            config_cls (type): The class that is not a dataclass.
        """
        super().__init__(f"{config_cls} must be a dataclass type")


class ModuleDidNotResolveToClassError(TypeError):
    """Exception raised when a module path does not resolve to a class."""

    def __init__(self, module_path: str) -> None:
        """Initialize with the module path that failed to resolve.

        Args:
            module_path (str): The module path that did not resolve to a class.
        """
        super().__init__(f"{module_path!r} did not resolve to a class")


class MustImplementError(TypeError):
    """Exception raised when a class does not implement the Transform interface."""

    def __init__(self, class_name: str, cls: type) -> None:
        """Initialize with the class name that failed to implement Transform.

        Args:
            class_name (str): The name of the class that must implement Transform.
            cls (type): The class or interface that must be implemented.
        """
        super().__init__(f"{class_name} must implement {cls}.")


class JavaHomeNotFoundError(ValueError):
    """Exception raised when the specified JAVA_HOME path does not exist or is not a directory."""

    def __init__(self, java_home: str) -> None:
        """Initialize the exception with the invalid JAVA_HOME path.

        Args:
            java_home (str): The JAVA_HOME path that does not exist or is not a directory.
        """
        super().__init__(f"java_home path does not exist or is not a directory: {java_home}")


class PipelineAbortError(RuntimeError):
    """Raised when a *stage* requests an immediate shutdown of the pipeline."""

    def __init__(self, message: str = "Pipeline aborted by stage request.") -> None:
        """Initialize the exception with an optional message.

        Args:
            message (str): The message describing the reason for aborting the pipeline.
        """
        super().__init__(message)
