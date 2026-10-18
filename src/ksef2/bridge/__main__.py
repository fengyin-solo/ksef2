"""Command line entry point for ``python -m ksef2.bridge``.

The only command is ``manifest``. With no flag it prints exactly the document
``ksef2.bridge.manifest()`` returns: ``json.dumps`` with sorted keys, two-space
indentation, and one trailing newline. Nothing else reaches standard output, so
the text can be piped straight into a JSON reader.

``manifest --write`` stores those same bytes in the committed snapshot at
``src/ksef2/bridge/manifest.json``. ``manifest --check`` compares that file to a
fresh generation: on success it prints nothing and exits ``0``; on failure it
prints a unified diff to standard error and exits ``1`` without touching the
file. Generation is deterministic, so ``--write`` run twice is byte-identical.
"""

import difflib
import sys
from collections.abc import Sequence
from pathlib import Path

from ksef2.bridge import manifest
from ksef2.bridge._manifest import render

SNAPSHOT_PATH: Path = Path(__file__).with_name("manifest.json")
"""Where the committed manifest snapshot lives, next to this module."""

USAGE = "usage: python -m ksef2.bridge manifest [--write | --check]\n"


def render_snapshot() -> str:
    """Render the committed manifest snapshot.

    Returns:
        The manifest as ``json.dumps`` with sorted keys, two-space indentation
        and one trailing newline. Two calls return the same bytes.
    """
    return render(manifest())


def write_snapshot(path: Path | None = None) -> bytes:
    """Write the manifest snapshot to *path*.

    Args:
        path: File to overwrite, defaulting to the committed snapshot inside
            the package.

    Returns:
        The bytes written.
    """
    target = SNAPSHOT_PATH if path is None else path
    text = render_snapshot()
    data = text.encode("utf-8")
    _ = target.write_bytes(data)
    return data


def check_snapshot(path: Path | None = None) -> str:
    """Compare a stored snapshot to a fresh generation.

    Args:
        path: File to read, defaulting to the committed snapshot inside the
            package. It is never modified.

    Returns:
        An empty string when the file matches a fresh generation, otherwise a
        unified diff from the stored file to what it should hold.
    """
    target = SNAPSHOT_PATH if path is None else path
    try:
        stored = target.read_text(encoding="utf-8")
    except OSError:
        stored = ""
    fresh = render_snapshot()
    if stored == fresh:
        return ""
    return "".join(
        difflib.unified_diff(
            stored.splitlines(keepends=True),
            fresh.splitlines(keepends=True),
            fromfile=str(target),
            tofile="freshly generated manifest",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the bridge command line.

    Args:
        argv: Arguments after the program name, defaulting to ``sys.argv``.

    Returns:
        ``0`` after printing or writing a matching manifest, ``1`` when
        ``--check`` found the snapshot stale, or ``2`` for a usage error.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments not in (
        ["manifest"],
        ["manifest", "--write"],
        ["manifest", "--check"],
    ):
        _ = sys.stderr.write(USAGE)
        return 2
    if arguments == ["manifest"]:
        _ = sys.stdout.write(render_snapshot())
        return 0
    if arguments == ["manifest", "--write"]:
        _ = write_snapshot()
        return 0
    diff = check_snapshot()
    if diff:
        _ = sys.stderr.write(diff)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
