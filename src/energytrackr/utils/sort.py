"""Sorts a CSV file containing commit hashes and energy values based on the commit history of a Git repository."""

import csv
import logging
import subprocess
import sys

EXPECTED_ROW_LENGTH = 6  # Number of columns expected in the CSV file

HEADER = ("commit", "energy-pkg", "energy-ram", "seconds", "temp_before", "temp_after")

def get_commit_history(repo_path: str) -> list[str]:
    """Retrieve the commit history from a Git repository in chronological order.

    Args:
        repo_path (str): The file system path to the Git repository.

    Returns:
        list[str]: A list of commit hashes in chronological order (oldest to newest).

    """
    try:
        result = subprocess.run(
            ["git", "rev-list", "--reverse", "--all"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        logging.exception("Error retrieving commit history.")
        sys.exit(1)
    return result.stdout.strip().split("\n")


def read_csv(file_path: str) -> tuple[bool, list[tuple]]:
    """Reads a CSV file containing commit hashes and energy values, preserving duplicate entries.

    Args:
        file_path (str): The path to the CSV file to read.

    Returns:
        tuple[bool, list[tuple]]: A tuple containing a boolean indicating the presence of a header and a list of tuples, each containing a commit hash and its corresponding energy values.
    """
    data: list[tuple] = []
    has_header = False
    with open(file_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            if len(row) == EXPECTED_ROW_LENGTH:
                if row[0] == "commit":
                    has_header = True
                    continue  # Skip header row
                data.append(tuple(row))  # Store as tuple to preserve duplicates
    return has_header, data


def write_csv(file_path: str, sorted_data: list[tuple[str, str, str, str, str, str]], has_header: bool) -> None:
    """Write the sorted commit data to a CSV file, preserving duplicates.

    Args:
        file_path (str): The path to the output CSV file.
        sorted_data (list[tuple[str, str, str, str, str, str]]): A list of tuples, each containing a commit
                                             identifier and its associated energy values.
        has_header (bool): Indicates whether the CSV file has a header row.
    """
    with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        if has_header:
            writer.writerow(HEADER)
        for row in sorted_data:
            writer.writerow(row)


def reorder_commits(csv_file: str, repo_path: str, output_file: str) -> None:
    """Reorders the rows of a CSV file containing commit hashes.

    Reorders the rows of a CSV file containing commit hashes to match the chronological order of
    commits in a Git repository, preserving duplicate entries, and writes the result to a new CSV file.

    Args:
        csv_file (str): Path to the input CSV file where the first column contains commit hashes.
        repo_path (str): Path to the local Git repository to retrieve commit history.
        output_file (str): Path to the output CSV file where the reordered data will be written.

    Notes:
        - Rows with commit hashes not found in the repository history are placed at the end of the output file.
        - Assumes the existence of helper functions: get_commit_history, read_csv, and write_csv.
    """
    commit_history = get_commit_history(repo_path)
    has_header, csv_data = read_csv(csv_file)

    # Sort the list while preserving duplicates
    commit_order = {commit: i for i, commit in enumerate(commit_history)}
    sorted_data = sorted(csv_data, key=lambda x: commit_order.get(x[0], float("inf")))

    write_csv(output_file, sorted_data, has_header)
    logging.info("Reordered CSV written to %s", output_file)
