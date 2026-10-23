"""Command line entry point of the bridge: ``python -m ksef2.bridge manifest``.

Prints the manifest of the public synchronous API as JSON on standard output, so
a binding generator in any language can read it without running Python. The
document is deterministic: the same public API always produces the same bytes.
"""

import argparse
import sys
from collections.abc import Sequence

from ksef2 import KSeFException
from ksef2.bridge._manifest import FORMAT_VERSION, manifest_json

_DESCRIPTION = "Describe the public ksef2 sync API as machine-readable data."
_PROGRAM = "python -m ksef2.bridge"


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the bridge command.

    Returns:
        A parser that accepts the ``manifest`` subcommand and its options.
    """
    parser = argparse.ArgumentParser(prog=_PROGRAM, description=_DESCRIPTION)
    subcommands = parser.add_subparsers(dest="command", required=True)
    manifest_command = subcommands.add_parser(
        "manifest",
        help="print the manifest of the public sync API as JSON",
        description=(
            "Print the manifest of the public sync API as JSON. The output is"
            f" format version {FORMAT_VERSION} and is valid JSON Schema 2020-12"
            " wherever it carries a schema."
        ),
    )
    _ = manifest_command.add_argument(
        "--indent",
        type=_indent,
        default=2,
        help="spaces per nesting level; 0 writes one compact line (default: 2)",
    )
    return parser


def _indent(value: str) -> int:
    """Return the indentation the command line asked for.

    Args:
        value: Text of the ``--indent`` argument.

    Returns:
        The number of spaces per nesting level.

    Raises:
        argparse.ArgumentTypeError: If the text is not a whole number, or is
            negative.
    """
    try:
        indent = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a whole number") from None
    if indent < 0:
        raise argparse.ArgumentTypeError("the manifest indent cannot be negative")
    return indent


def main(argv: Sequence[str] | None = None) -> int:
    """Run the bridge command.

    Args:
        argv: Arguments after the program name; ``None`` reads ``sys.argv``.

    Returns:
        ``0`` after printing the manifest, ``1`` when the manifest cannot be
        built, or ``2`` when the arguments are wrong.
    """
    parser = build_parser()
    arguments = parser.parse_args(argv)
    command: object = getattr(arguments, "command", None)
    indent: object = getattr(arguments, "indent", 2)
    if isinstance(command, str) and command != "manifest":
        parser.error(f"unknown command {command!r}")
    try:
        document = manifest_json(indent=indent if isinstance(indent, int) else 2)
    except KSeFException as error:
        print(f"{_PROGRAM}: {error}", file=sys.stderr)
        return 1
    print(document)
    return 0


if __name__ == "__main__":
    sys.exit(main())
