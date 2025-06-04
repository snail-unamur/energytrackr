"""Energy Pipeline CLI."""

from energytrackr.commands.args_parser import parse_args
from energytrackr.commands.dispatcher import handle_command


def main() -> None:
    """Main entry point for the Energy Pipeline CLI."""
    args = parse_args()
    handle_command(args)


if __name__ == "__main__":
    main()
