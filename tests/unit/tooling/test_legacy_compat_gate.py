import json
from pathlib import Path

import pytest

from scripts import check_legacy_compat as gate


@pytest.mark.parametrize(
    ("legacy_modules", "stable_modules", "expected_status", "expected_output"),
    [
        (["ksef2.removed_before_1"], ["ksef2.renderers"], 0, "verify 1.x: 0 missing"),
        (
            ["ksef2.removed_before_1"],
            ["ksef2.removed_before_1"],
            1,
            "MISSING module ksef2.removed_before_1 (baseline ksef2==1.0.0)",
        ),
        (
            ["ksef2.renderers"],
            ["ksef2.renderers"],
            1,
            "STALE allowlist entry tree ksef2.removed_before_1",
        ),
    ],
)
def test_gate_checks_all_baselines_without_waiving_1x_removals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    legacy_modules: list[str],
    stable_modules: list[str],
    expected_status: int,
    expected_output: str,
) -> None:
    # Unit tests run against an editable install. The full gate separately
    # verifies installed distributions in isolated site-packages environments.
    monkeypatch.setattr(gate, "_assert_environment", lambda **kwargs: tmp_path)
    snapshots: list[str] = []
    for version, modules in [("0.22.2", legacy_modules), ("1.0.0", stable_modules)]:
        path = tmp_path / f"{version}.json"
        _ = path.write_text(
            json.dumps(
                {
                    "baseline": version,
                    "modules": dict.fromkeys(modules, []),
                    "classes": {},
                    "class_attributes": {},
                }
            )
        )
        snapshots.append(str(path))
    allowlist = tmp_path / "allowlist.toml"
    _ = allowlist.write_text(
        '[[entry]]\npath = "ksef2.removed_before_1"\nkind = "tree"\n'
        'reason = "Removed before the 1.x compatibility contract."\n'
    )

    assert (
        gate.main(["verify", "--snapshot", *snapshots, "--allowlist", str(allowlist)])
        == expected_status
    )
    assert expected_output in capsys.readouterr().out
