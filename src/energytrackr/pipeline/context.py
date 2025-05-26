"""EnergyTrackr pipeline context."""

from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass, field
from typing import Any

from git import Commit, Repo


@dataclass(slots=False, kw_only=True)
class Context(MutableMapping[str, Any]):
    """Typed view over the shared dictionary passed to every stage.

    The class fully implements :pyclass:`collections.abc.MutableMapping` so it
    remains backward-compatible with legacy code expecting a plain ``dict``.

    Attributes:
    ----------
    commit
        The *current* Git commit (lazy-resolved).
    repo_path
        Absolute path of the cloned repository.
    commits
        Optional list of *all* commits under inspection (may shrink).
    energy_value
        Energy consumption result produced by
        :class:`~energytrackr.pipeline.core_stages.measure_stage.MeasureEnergyStage`.
    build_failed
        Flag set by :class:`BuildStage` if compilation failed.
    abort_pipeline
        Flag that forces a graceful shutdown when *True*.
    worker_process
        Internal hint - *True* when running in a multiprocess worker.
    """

    commit: str
    repo_path: str
    commits: list[str] | None = None
    energy_value: float | None = None
    build_failed: bool = False
    abort_pipeline: bool = False
    worker_process: bool = False
    log_buffer: list[tuple[int, str, tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)

    def __getitem__(self, key: str) -> Any:
        """Return the value of the attribute with the given key."""
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        """Set the value of the attribute with the given key."""
        setattr(self, key, value)

    def __delitem__(self, key: str) -> None:
        """Delete the attribute with the given key."""
        delattr(self, key)

    def __iter__(self) -> Iterator[str]:
        """Return an iterator over the context's attribute names."""
        return iter(self.__dict__)

    def __len__(self) -> int:
        """Return the number of attributes in the context."""
        return len(self.__dict__)

    def __contains__(self, key: object) -> bool:
        """Check if the context contains an attribute with the given key.

        Args:
            key: The key to check for.

        Returns:
            bool: True if the context contains the key, False otherwise.
        """
        return hasattr(self, str(key))

    def get(self, key: str, default: Any | None = None) -> Any:
        """Return the value for key if key is in the context, else default.

        Args:
            key: The key to look up.
            default: The value to return if key is not found.

        Returns:
            The value associated with key if present, otherwise default.
        """
        return getattr(self, key, default)

    def get_commit(self) -> Commit:
        """Return the current commit SHA.

        Returns:
            Commit: The commit object for the current commit.
        """
        # Reopen the repo to get the commit object
        repo = Repo(self.repo_path)
        return repo.commit(self.commit)

    def get_commits(self) -> list[Commit]:
        """Return the list of commits.

        Returns:
            list[Commit]: A list of commit objects for the commits.
        """
        if self.commits is None:
            return []
        # Reopen the repo to get the commit objects
        repo = Repo(self.repo_path)
        return [repo.commit(c) for c in self.commits]
