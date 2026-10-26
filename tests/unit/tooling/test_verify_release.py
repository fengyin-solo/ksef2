import io
import shutil
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.verify_release import verify_release


def write_release_fixture(root: Path, *, version: str, wheel_version: str) -> Path:
    source = Path(__file__).parents[3] / "schemas/FA3"
    schema_directory = root / "schemas/FA3"
    schema_directory.mkdir(parents=True)
    for path in [source / "code-lists.json", *source.glob("Kody*.xsd")]:
        _ = shutil.copyfile(path, schema_directory / path.name)
    (root / "dist").mkdir()
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "ksef2"\nversion = "{version}"\n'
    )
    (root / "CHANGELOG.md").write_text(f"## v{version} (2026-07-10)\n")
    with tarfile.open(root / f"dist/ksef2-{version}.tar.gz", "w:gz") as archive:
        for path in schema_directory.iterdir():
            for directory in ("schemas/FA3", "src/ksef2/_infra/schema/fa3/definitions"):
                archive.add(path, arcname=f"ksef2-{version}/{directory}/{path.name}")

    wheel = root / f"dist/ksef2-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path in schema_directory.iterdir():
            archive.write(path, f"ksef2/_infra/schema/fa3/definitions/{path.name}")
        archive.writestr(
            f"ksef2-{wheel_version}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: ksef2\nVersion: {wheel_version}\n",
        )
    return root / "dist"


@pytest.mark.parametrize("artifact", ["wheel", "sdist"])
@pytest.mark.parametrize("corruption", ["missing", "changed"])
def test_verify_release_rejects_missing_or_changed_code_lists(
    tmp_path: Path, artifact: str, corruption: str
) -> None:
    dist = write_release_fixture(tmp_path, version="1.0.0", wheel_version="1.0.0")
    name = "KodyWalut_v1-0E.xsd"
    if artifact == "wheel":
        path = dist / "ksef2-1.0.0-py3-none-any.whl"
        with zipfile.ZipFile(path) as archive:
            contents = {member: archive.read(member) for member in archive.namelist()}
        with zipfile.ZipFile(path, "w") as archive:
            for member, content in contents.items():
                if member.endswith(name):
                    if corruption == "changed":
                        archive.writestr(member, b"changed")
                else:
                    archive.writestr(member, content)
    else:
        path = dist / "ksef2-1.0.0.tar.gz"
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            contents = {}
            for member in members:
                source = archive.extractfile(member)
                assert source is not None
                contents[member.name] = source.read()
        with tarfile.open(path, "w:gz") as archive:
            for member in members:
                content = contents[member.name]
                if member.name.endswith(name):
                    if corruption == "missing":
                        continue
                    content = b"changed"
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))

    errors = verify_release(tag="v1.0.0", root=tmp_path, dist_directory=dist)

    assert any(artifact in error and name in error for error in errors)


def test_verify_release_rejects_code_list_checksum_mismatch(tmp_path: Path) -> None:
    dist = write_release_fixture(tmp_path, version="1.0.0", wheel_version="1.0.0")
    (tmp_path / "schemas/FA3/KodyWalut_v1-0E.xsd").write_bytes(b"changed")

    errors = verify_release(tag="v1.0.0", root=tmp_path, dist_directory=dist)

    assert "bundled code-list checksum mismatch: KodyWalut_v1-0E.xsd" in errors


def test_verify_release_accepts_matching_tag_and_artifacts(
    tmp_path: Path,
) -> None:
    dist_directory = write_release_fixture(
        tmp_path, version="1.0.0", wheel_version="1.0.0"
    )

    assert (
        verify_release(tag="v1.0.0", root=tmp_path, dist_directory=dist_directory) == []
    )


def test_verify_release_reports_tag_and_wheel_mismatches(tmp_path: Path) -> None:
    dist_directory = write_release_fixture(
        tmp_path, version="1.0.0", wheel_version="0.19.0"
    )

    errors = verify_release(tag="v0.19.0", root=tmp_path, dist_directory=dist_directory)

    assert "tag 'v0.19.0' does not match project version 'v1.0.0'" in errors
    assert "wheel metadata declares '0.19.0', expected '1.0.0'" in errors


@pytest.mark.parametrize(
    ("heading", "expected_error"),
    [
        (
            "## v1.0.0 (unreleased)",
            "CHANGELOG.md release heading must contain a YYYY-MM-DD date",
        ),
        (
            "## v1.0.0 (YYYY-MM-DD)",
            "CHANGELOG.md release heading must contain a YYYY-MM-DD date",
        ),
        (
            "## v1.0.0 (2026-02-30)",
            "CHANGELOG.md release heading contains an invalid date",
        ),
        (
            "## v1.0.0 (2026-7-10)",
            "CHANGELOG.md release heading must contain a YYYY-MM-DD date",
        ),
        (
            "## v1.0.0 (2026-07-10) draft",
            "CHANGELOG.md release heading must contain a YYYY-MM-DD date",
        ),
    ],
)
def test_verify_release_rejects_unfinished_or_invalid_release_date(
    tmp_path: Path, heading: str, expected_error: str
) -> None:
    dist_directory = write_release_fixture(
        tmp_path, version="1.0.0", wheel_version="1.0.0"
    )
    (tmp_path / "CHANGELOG.md").write_text(heading + "\n")

    errors = verify_release(tag="v1.0.0", root=tmp_path, dist_directory=dist_directory)

    assert errors == [expected_error]
