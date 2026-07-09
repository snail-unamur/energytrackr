"""Test cases for the core functionality of the pipeline."""

import argparse
from pathlib import Path

import git
import pytest
import yaml
from git import Commit, Repo

from energytrackr.config.config_store import Config
from energytrackr.config.loader import load_pipeline_config
from energytrackr.pipeline.pipeline import compile_stages
from energytrackr.utils.args_parser import parse_args
from energytrackr.utils.git_utils import clone_or_open_repo, gather_commits


def test_clone_or_open_repo(tmp_path: Path) -> None:
    """Test cloning or opening a Git repository."""
    repo_dir: Path = tmp_path / "dummy_repo"
    repo_dir.mkdir()
    repo: Repo = git.Repo.init(str(repo_dir))

    test_file: Path = repo_dir / "test.txt"
    test_file.write_text("Hello")
    repo.index.add([str(test_file)])
    repo.index.commit("Initial commit")

    returned_repo: Repo = clone_or_open_repo(str(repo_dir), "dummy_url")
    assert returned_repo.working_tree_dir == str(repo_dir)


def test_gather_commits(tmp_path: Path) -> None:
    """Test gathering commits from a Git repository."""
    Config.reset()

    # Step 1: Create a dummy Git repo with 3 commits
    repo_dir: Path = tmp_path / "test_repo"
    repo: Repo = git.Repo.init(str(repo_dir), initial_branch="master")
    commit_hashes: list[str] = []

    for i in range(3):
        file_path: Path = repo_dir / f"file{i}.txt"
        file_path.write_text(f"Content {i}")
        repo.index.add([str(file_path)])
        commit: Commit = repo.index.commit(f"Commit {i}")
        commit_hashes.append(commit.hexsha)

    # Step 2: Load base config from tests/sample_conf.yml
    sample_path = Path(__file__).parent / "config/sample_conf.yml"
    config_dict = yaml.safe_load(sample_path.read_text())

    # Step 3: Patch repo URL and branch to point to temp repo
    config_dict["repo"]["url"] = str(repo_dir)
    config_dict["repo"]["branch"] = "master"
    config_dict["execution_plan"]["granularity"] = "commits"
    config_dict["execution_plan"]["num_commits"] = 3

    config_file: Path = tmp_path / "config.yml"
    config_file.write_text(yaml.safe_dump(config_dict))

    # Step 4: Run test logic
    load_pipeline_config(str(config_file))
    commits: list[Commit] = gather_commits(repo)

    # Step 5: Assertions
    expected_commit_count = 3
    assert len(commits) <= expected_commit_count
    commit_shas: list[str] = [c.hexsha for c in commits]
    assert any(sha in commit_shas for sha in commit_hashes)


def test_gather_commits_branches(tmp_path: Path) -> None:
    """Test gathering commits from multiple branches in a Git repository."""
    Config.reset()

    # Create a repo
    repo_dir = tmp_path / "repo"
    repo = Repo.init(repo_dir, initial_branch="main")

    # Add first commit on main
    (repo_dir / "main.txt").write_text("main branch")
    repo.index.add(["main.txt"])
    repo.index.commit("main commit")

    # Create a second branch
    repo.git.checkout("-b", "feature")
    (repo_dir / "feature.txt").write_text("feature branch")
    repo.index.add(["feature.txt"])
    repo.index.commit("feature commit")

    # Return to main
    repo.git.checkout("main")

    # Create remote pointing to itself
    repo.create_remote("origin", str(repo_dir))

    # Push both branches to origin so refs exist
    repo.remotes.origin.push(refspec="main:main")
    repo.remotes.origin.push(refspec="feature:feature")

    # Create config
    config = {
        "repo": {"url": str(repo_dir), "branch": "main", "clone_options": []},
        "execution_plan": {
            "mode": "tests",
            "granularity": "branches",
            "test_command": "pytest",
            "test_command_path": ".",
            "ignore_failures": True,
            "num_commits": 5,
            "num_runs": 1,
            "num_repeats": 1,
            "batch_size": 2,
            "randomize_tasks": False,
        },
        "limits": {"temperature_safe_limit": 90000, "energy_regression_percent": 15},
        "tracked_file_extensions": ["py"],
        "cpu_thermal_file": "/sys/class/thermal/thermal_zone0/temp",
        "setup_commands": [],
        "results": {"file": "results.csv"},
    }

    config_path = tmp_path / "config.yml"
    config_path.write_text(yaml.safe_dump(config))
    load_pipeline_config(str(config_path))

    commits = gather_commits(repo)

    # Now it should return 2 commits: one per branch
    expected_commits_count = 2
    assert len(commits) == expected_commits_count


def test_gather_commits_tags(tmp_path: Path) -> None:
    """Test gathering commits from tags in a Git repository."""
    Config.reset()
    repo_dir = tmp_path / "tag_repo"
    repo = git.Repo.init(str(repo_dir), initial_branch="main")

    # 3 commits, 2 tags
    for i in range(3):
        path = repo_dir / f"f{i}.txt"
        path.write_text(str(i))
        repo.index.add([str(path)])
        repo.index.commit(f"Commit {i}")
    repo.create_tag("v1", ref=repo.head.commit)
    repo.create_tag("v2", ref=repo.commit("HEAD~1"))

    config = {
        "repo": {"url": str(repo_dir), "branch": "main", "clone_options": []},
        "execution_plan": {
            "mode": "tests",
            "granularity": "tags",  # 🔥
            "test_command": "pytest",
            "test_command_path": ".",
            "ignore_failures": True,
            "num_commits": 1,
            "num_runs": 1,
            "num_repeats": 1,
            "batch_size": 1,
            "randomize_tasks": False,
        },
        "limits": {"temperature_safe_limit": 90000, "energy_regression_percent": 15},
        "tracked_file_extensions": ["py"],
        "cpu_thermal_file": "/sys/class/thermal/thermal_zone0/temp",
        "setup_commands": [],
        "results": {"file": "results.csv"},
    }

    config_file = tmp_path / "config.yml"
    config_file.write_text(yaml.safe_dump(config))
    load_pipeline_config(str(config_file))

    commits = gather_commits(repo)
    expected_commits_count = 2
    assert len(commits) == expected_commits_count  # one per tag


def test_gather_commits_oldest_and_newest(tmp_path: Path) -> None:
    """Test gathering commits with oldest and newest commit bounds."""
    Config.reset()

    # Create a dummy Git repo with 4 commits
    repo_dir = tmp_path / "repo"
    repo: Repo = Repo.init(repo_dir, initial_branch="main")

    for i in range(4):
        file = repo_dir / f"file{i}.txt"
        file.write_text(f"content {i}")
        repo.index.add([str(file)])
        repo.index.commit(f"commit {i}")

    # Get all SHAs in reverse chronological order (newest-first)
    all_commits = list(repo.iter_commits("main"))
    sha_list = [commit.hexsha for commit in all_commits]

    # Selecting bounds from the descending list.
    # To have a proper chronological range, oldest must be older than newest.
    # In the descending list:
    #   Index 1 is commit2 and index 2 is commit1.
    # So we swap them:
    oldest = sha_list[2]  # commit1 (older chronologically)
    newest = sha_list[1]  # commit2 (newer chronologically)

    config = {
        "repo": {"url": str(repo_dir), "branch": "main", "clone_options": []},
        "execution_plan": {
            "mode": "tests",
            "granularity": "commits",
            "test_command": "pytest",
            "test_command_path": ".",
            "ignore_failures": True,
            "num_commits": 2,  # To match the number of commits in the range
            "num_runs": 1,
            "num_repeats": 1,
            "batch_size": 2,
            "randomize_tasks": False,
            "oldest_commit": oldest,
            "newest_commit": newest,
        },
        "limits": {"temperature_safe_limit": 90000, "energy_regression_percent": 15},
        "tracked_file_extensions": ["py"],
        "cpu_thermal_file": "/sys/class/thermal/thermal_zone0/temp",
        "setup_commands": [],
        "results": {"file": "results.csv"},
    }

    config_path = tmp_path / "config.yml"
    config_path.write_text(yaml.safe_dump(config))
    load_pipeline_config(str(config_path))

    # Run and extract resulting commits
    selected_commits = gather_commits(repo)
    selected_shas = [c.hexsha for c in selected_commits]

    # Debugging: print both lists if needed

    # Assertions: the specified oldest and newest commits should both be in the selection
    assert oldest in selected_shas
    assert newest in selected_shas
    expected_commit_count = 2
    assert len(selected_shas) == expected_commit_count


def test_compile_stages() -> None:
    """Test the compile_stages function."""
    stages: dict[str, str] = compile_stages()
    for key in ["pre_stages", "pre_test_stages", "batch_stages"]:
        assert key in stages
        assert isinstance(stages[key], list)


def test_parse_args_measure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test parsing arguments for the measure command."""
    test_args: list[str] = ["measure", "--config", "test.yml"]
    monkeypatch.setattr("sys.argv", ["main.py", *test_args])
    args = parse_args()
    assert args.command == "measure"
    assert args.config == "test.yml"


def test_parse_args_sort(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test parsing arguments for the sort command."""
    test_args: list[str] = ["sort", "input.csv", "repo_path", "output.csv"]
    monkeypatch.setattr("sys.argv", ["main.py", *test_args])
    args = parse_args()
    assert args.command == "sort"
    assert args.file == "input.csv"
    assert args.repo_path == "repo_path"
    assert args.output_file == "output.csv"


def make_args(**kwargs: dict[str, object]) -> argparse.Namespace:
    """Helper to create argparse.Namespace for tests.

    Args:
        **kwargs (dict[str, object]): Keyword arguments to set as attributes.

    Returns:
        argparse.Namespace: An object with the specified attributes.
    """
    return argparse.Namespace(**kwargs)
