"""Verify release metadata and bundled code-list artifacts in built distributions."""

import argparse
import hashlib
import json
import re
import sys
import tarfile
import tomllib
import zipfile
from datetime import date
from email.parser import Parser
from pathlib import Path
from typing import cast


ROOT = Path(__file__).resolve().parent.parent


def verify_release(*, tag: str, root: Path, dist_directory: Path) -> list[str]:
    """Return release metadata mismatches without publishing any artifact."""
    errors: list[str] = []

    with (root / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = cast(dict[str, object], tomllib.load(pyproject_file))
    project = cast(dict[str, object], pyproject["project"])
    project_version = cast(str, project["version"])

    expected_tag = f"v{project_version}"

    if tag != expected_tag:
        errors.append(f"tag {tag!r} does not match project version {expected_tag!r}")
    changelog_heading = f"## v{project_version} "
    changelog = (root / "CHANGELOG.md").read_text()
    if not changelog.startswith(changelog_heading):
        errors.append(
            f"CHANGELOG.md must start with a {changelog_heading.strip()!r} heading"
        )
    else:
        heading = changelog.splitlines()[0]
        date_match = re.fullmatch(
            re.escape(changelog_heading) + r"\((\d{4}-\d{2}-\d{2})\)", heading
        )
        if date_match is None:
            errors.append("CHANGELOG.md release heading must contain a YYYY-MM-DD date")
        else:
            try:
                _ = date.fromisoformat(date_match[1])
            except ValueError:
                errors.append("CHANGELOG.md release heading contains an invalid date")

    errors.extend(verify_artifacts(root=root, dist_directory=dist_directory))
    return errors


def verify_artifacts(*, root: Path, dist_directory: Path) -> list[str]:
    """Verify distribution metadata and bundled code-list bytes without network access."""
    errors: list[str] = []
    with (root / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = cast(dict[str, object], tomllib.load(pyproject_file))
    project = cast(dict[str, object], pyproject["project"])
    project_version = cast(str, project["version"])

    source_directory = root / "schemas/FA3"
    manifest = (source_directory / "code-lists.json").read_bytes()
    records = cast(list[dict[str, str]], json.loads(manifest))
    expected_files = {"code-lists.json": manifest}
    for record in records:
        name = record["file"]
        content = (source_directory / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != record["sha256"]:
            errors.append(f"bundled code-list checksum mismatch: {name}")
        expected_files[name] = content

    wheels = sorted(dist_directory.glob(f"ksef2-{project_version}-*.whl"))
    if len(wheels) != 1:
        errors.append(
            f"expected exactly one ksef2 {project_version} wheel, found {len(wheels)}"
        )
    else:
        with zipfile.ZipFile(wheels[0]) as wheel:
            for name, expected in expected_files.items():
                member = f"ksef2/_infra/schema/fa3/definitions/{name}"
                if member not in wheel.namelist():
                    errors.append(
                        f"wheel is missing bundled code-list artifact: {name}"
                    )
                elif wheel.read(member) != expected:
                    errors.append(f"wheel bundled code-list artifact differs: {name}")
            metadata_files = [
                name
                for name in wheel.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_files) != 1:
                errors.append(
                    f"expected one METADATA file in {wheels[0].name}, "
                    f"found {len(metadata_files)}"
                )
            else:
                metadata = Parser().parsestr(
                    wheel.read(metadata_files[0]).decode("utf-8")
                )
                wheel_version = metadata.get("Version")
                if wheel_version != project_version:
                    errors.append(
                        f"wheel metadata declares {wheel_version!r}, "
                        f"expected {project_version!r}"
                    )

    source_distributions = sorted(
        dist_directory.glob(f"ksef2-{project_version}.tar.gz")
    )
    if len(source_distributions) != 1:
        errors.append(
            f"expected exactly one ksef2 {project_version} source distribution, "
            f"found {len(source_distributions)}"
        )
    else:
        with tarfile.open(source_distributions[0], "r:gz") as sdist:
            for name, expected in expected_files.items():
                for directory in (
                    "schemas/FA3",
                    "src/ksef2/_infra/schema/fa3/definitions",
                ):
                    member = f"ksef2-{project_version}/{directory}/{name}"
                    try:
                        source_file = sdist.extractfile(member)
                    except KeyError:
                        source_file = None
                    if source_file is None:
                        errors.append(
                            f"sdist is missing bundled code-list artifact: {directory}/{name}"
                        )
                    elif source_file.read() != expected:
                        errors.append(
                            f"sdist bundled code-list artifact differs: {directory}/{name}"
                        )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    _ = mode.add_argument("--tag", help="Git tag, for example v1.0.0")
    _ = mode.add_argument(
        "--artifacts-only",
        action="store_true",
        help="verify built artifacts before release version and changelog preparation",
    )
    _ = parser.add_argument(
        "--dist-directory",
        type=Path,
        default=ROOT / "dist",
        help="Directory containing the wheel and source distribution",
    )
    args = parser.parse_args()
    tag = cast(str | None, args.tag)
    dist_directory = cast(Path, args.dist_directory)

    if tag is None:
        errors = verify_artifacts(root=ROOT, dist_directory=dist_directory)
    else:
        errors = verify_release(tag=tag, root=ROOT, dist_directory=dist_directory)
    if errors:
        for error in errors:
            print(f"release verification failed: {error}", file=sys.stderr)
        return 1

    print(f"release artifacts verified{f' for {tag}' if tag else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
