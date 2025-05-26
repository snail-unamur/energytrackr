"""Git utility functions for cloning repositories and gathering commits."""

import os
from pathlib import Path
from typing import Any

from git import Commit, Repo

from energytrackr.config.config_store import Config
from energytrackr.utils.logger import logger


def clone_or_open_repo(repo_path: Path, repo_url: str, clone_options: list[str] | None = None) -> Repo:
    """Clone a Git repository from a URL or open an existing repository from a local path.

    Args:
        repo_path (str): The local path where the repository should be cloned or opened.
        repo_url (str): The URL of the remote Git repository.
        clone_options (list, optional): Additional options to pass to the clone command.

    Returns:
        git.Repo: An instance of the Git repository at the specified path.
    """
    if not os.path.exists(repo_path):
        logger.info("Cloning %s into %s", repo_url, repo_path)
        clone_opts = clone_options or []
        return Repo.clone_from(repo_url, repo_path, multi_options=clone_opts)
    logger.info("Using existing repo at %s", repo_path)
    return Repo(repo_path)


def gather_commits(repo: Repo) -> list[Commit]:
    """Gather the commits that should be processed according to the execution plan.

    For branches, we just take one commit per branch. For tags, we take the num_commits newest
    commits for each tag. For commits, we take the specified number of commits from the specified
    branch, starting from the oldest commit. If oldest_commit is specified, we start from there.
    If newest_commit is specified, we stop at that commit.

    Args:
        repo (git.Repo): The git repository to gather commits from.

    Returns:
        list[git.Commit]: The list of commits to process.
    """
    conf = Config.get_config()
    plan = conf.execution_plan

    if plan.granularity == "branches":
        # One commit per branch
        branches = list(repo.remotes.origin.refs)
        return [branch.commit for branch in branches]

    if plan.granularity == "tags":
        tags = list(repo.tags)
        commits: list[Commit] = []
        for tag in tags:
            commits.extend(list(repo.iter_commits(tag, max_count=plan.num_commits)))
        return commits

    # commits granularity
    # Get all commits from the branch in descending order (newest-first)
    if not conf.repo.branch or conf.repo.branch not in repo.branches:
        logger.warning("Branch %s not found in the repository. Using default branch.", conf.repo.branch)
        conf.repo.branch = repo.active_branch.name
    commits = list(repo.iter_commits(conf.repo.branch))
    # Reverse to get ascending order (oldest-first) to make filtering more intuitive
    commits = list(reversed(commits))

    # If an oldest_commit is specified, start from that commit onward.
    if plan.oldest_commit:
        if (start_idx := next((i for i, c in enumerate(commits) if c.hexsha == plan.oldest_commit), None)) is not None:
            commits = commits[start_idx:]
        else:
            logger.warning("Oldest commit %s not found in commit history.", plan.oldest_commit)

    # If a newest_commit is specified, stop at that commit (inclusive)
    if plan.newest_commit:
        if (end_idx := next((i for i, c in enumerate(commits) if c.hexsha == plan.newest_commit), None)) is not None:
            commits = commits[: end_idx + 1]
        else:
            logger.warning("Newest commit %s not found in commit history.", plan.newest_commit)

    # If a number of commits is specified, take the most recent num_commits from the ascending list.
    # Since the list is ascending (oldest-first), we slice from the tail to keep the latest commits.
    if plan.num_commits:
        commits = commits[-plan.num_commits :]

    logger.info("Gathered %d commits from branch %s", len(commits), conf.repo.branch)

    return commits


def generate_commit_link(remote_url: str, commit_hash: str) -> str:
    """Generate a URL to view a specific commit on a remote Git repository.

    Given a remote repository URL (either SSH or HTTPS) and a commit hash,
    this function constructs a direct link to the commit on platforms that use
    GitHub-style URLs.

    Args:
        remote_url (str): The remote repository URL (SSH or HTTPS).
        commit_hash (str): The commit hash to link to.

    Returns:
        str: The URL to view the commit, or "N/A" if the URL format is unsupported.

    Examples:
        >>> generate_commit_link("git@github.com:user/repo.git", "abc123")
        'https://github.com/user/repo/commit/abc123'
        >>> generate_commit_link("https://github.com/user/repo.git", "abc123")
        'https://github.com/user/repo/commit/abc123'
    """
    if remote_url.startswith("git@"):
        parts = remote_url.split(":")
        expected_num_parts = 2
        if len(parts) != expected_num_parts:
            return "N/A"
        domain_part = parts[0]
        repo_part = parts[1]
        if "@" not in domain_part or not repo_part.endswith(".git"):
            return "N/A"
        domain = domain_part.split("@")[-1]
        repo_path = repo_part[:-4]  # remove ".git"
        return f"https://{domain}/{repo_path}/commit/{commit_hash}"
    if remote_url.startswith("https://"):
        repo_url = remote_url[:-4] if remote_url.endswith(".git") else remote_url
        return f"{repo_url}/commit/{commit_hash}"
    return "N/A"


def get_commit_details_from_git(commit_hash: str, repo: Repo) -> dict[str, Any]:
    """Retrieve details about a specific git commit from a repository.

    Args:
        commit_hash (str): The hash of the commit to retrieve details for.
        repo (Repo): An instance of a GitPython Repo object representing the repository.

    Returns:
        dict[str, Any]: A dictionary containing the following keys:
            - "commit_summary" (str): The summary message of the commit.
            - "commit_link" (str): A URL to view the commit in a remote repository, or "N/A" if unavailable.
            - "commit_date" (str): The date of the commit in "YYYY-MM-DD" format.
            - "files_modified" (list[str]): A list of file paths modified in the commit.

    If an error occurs, returns a dictionary with "N/A" or empty values for all fields.
    """
    try:
        commit_obj = repo.commit(commit_hash)
    except Exception:
        logger.exception("Error retrieving details for commit %s", commit_hash)
        return {"commit_summary": "N/A", "commit_link": "N/A", "commit_date": "N/A", "files_modified": []}

    commit_date = commit_obj.committed_datetime.strftime("%Y-%m-%d")
    commit_summary = commit_obj.summary
    commit_message = commit_obj.message
    commit_files = list(commit_obj.stats.files.keys())
    commit_link = "N/A"
    if repo.remotes:
        remote_url = repo.remotes[0].url
        commit_link = generate_commit_link(remote_url, commit_hash)

    return {
        "commit_summary": commit_summary,
        "commit_message": commit_message,
        "commit_link": commit_link,
        "commit_date": commit_date,
        "files_modified": commit_files,
    }
