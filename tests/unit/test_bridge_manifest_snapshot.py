"""The committed bridge manifest snapshot: bytes, determinism, the check, packaging."""

import importlib.resources
import json
from pathlib import Path
from typing import Any, cast

import pytest

import ksef2.bridge.__main__ as bridge_main
from ksef2.bridge import manifest


def _expected_text() -> str:
    """The text the committed snapshot must hold.

    Returns:
        The manifest as sorted, two-space-indented JSON with one trailing
        newline, exactly what ``python -m ksef2.bridge manifest`` prints.
    """
    return json.dumps(manifest(), sort_keys=True, indent=2) + "\n"


def test_committed_manifest_matches_manifest() -> None:
    stored = bridge_main.SNAPSHOT_PATH.read_bytes()

    assert stored == _expected_text().encode("utf-8")


def test_generating_twice_is_byte_identical(tmp_path: Path) -> None:
    first = bridge_main.write_snapshot(tmp_path / "first.json")
    second = bridge_main.write_snapshot(tmp_path / "second.json")

    assert first == second
    assert first == _expected_text().encode("utf-8")


def test_check_fails_with_a_diff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stale = tmp_path / "manifest.json"
    data = cast("dict[str, Any]", json.loads(_expected_text()))
    operations = cast("list[dict[str, Any]]", data["operations"])
    original_id = cast("str", operations[0]["id"])
    operations[0]["id"] = "changed.operation"
    _ = stale.write_text(
        json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(bridge_main, "SNAPSHOT_PATH", stale)

    exit_code = bridge_main.main(["manifest", "--check"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert any(line.startswith("---") for line in captured.err.splitlines())
    assert any(line.startswith("+++") for line in captured.err.splitlines())
    assert any(line.startswith("@@") for line in captured.err.splitlines())
    # The stored file is the diff's "from" side, the fresh generation its "to" side.
    removed = [
        line
        for line in captured.err.splitlines()
        if line.startswith("-") and "changed.operation" in line
    ]
    added = [
        line
        for line in captured.err.splitlines()
        if line.startswith("+") and original_id in line
    ]
    assert removed
    assert added
    # The check reports the staleness and never repairs the file it read.
    assert stale.read_text(encoding="utf-8") != _expected_text()


def test_packaged_manifest_is_readable() -> None:
    packaged = (
        importlib.resources.files("ksef2.bridge")
        .joinpath("manifest.json")
        .read_text(encoding="utf-8")
    )

    assert packaged == bridge_main.SNAPSHOT_PATH.read_text(encoding="utf-8")
    assert json.loads(packaged) == manifest()
