"""Command line entry point for ``python -m ksef2.bridge``.

The only command is ``manifest``, which prints exactly the document
``ksef2.bridge.manifest()`` returns: ``json.dumps`` with sorted keys, two-space
indentation, and one trailing newline. Nothing else reaches standard output, so
the text can be piped straight into a JSON reader.
"""

import sys
from collections.abc import Sequence

from ksef2.bridge import manifest
from ksef2.bridge._manifest import render

USAGE = "usage: python -m ksef2.bridge manifest\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the bridge command line.

    Args:
        argv: Arguments after the program name, defaulting to ``sys.argv``.

    Returns:
        ``0`` after printing the manifest, or ``2`` for a usage error.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments != ["manifest"]:
        _ = sys.stderr.write(USAGE)
        return 2
    _ = sys.stdout.write(render(manifest()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
