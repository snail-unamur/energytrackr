"""Command-line argument parser for the Energy Pipeline CLI."""

import argparse


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description="Energy Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Subcommand to run")

    # measure subcommand
    measure_parser = subparsers.add_parser("measure", help="Run energy measurement")
    measure_parser.add_argument("--config", default="config.yml", help="Path to config file")

    # sort subcommand
    sort_parser = subparsers.add_parser("sort", help="Sort a result file")
    sort_parser.add_argument("file", help="Path to the result file to sort")
    sort_parser.add_argument("repo_path", help="Path to the repository")
    sort_parser.add_argument("output_file", help="Path to the output file")

    # plot subcommand
    plot_parser = subparsers.add_parser("plot", help="Plot a result file")
    plot_parser.add_argument("file", help="Path to the result file to plot")
    plot_parser.add_argument("repo_path", help="Path to the repository")
    plot_parser.add_argument("--config", default="plot.yml", help="Path to config file")

    return parser.parse_args()
