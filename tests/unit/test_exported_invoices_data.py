"""``ExportedInvoicesData``: snapshot, JSON round trip and rebuilt behaviour."""

import base64
import io
import json
import stat
import tarfile
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from polyfactory import BaseFactory
from pydantic import ValidationError

import ksef2.clients
import ksef2.models
from ksef2 import KSeFValidationError
from ksef2._infra.schema.api import spec
from ksef2.clients import ExportedInvoices
from ksef2.models import (
    ExportedInvoicesData,
    InvoiceMetadata,
    InvoicePackage,
    PackagePart,
)
from tests.unit.test_exported_invoices import (
    KSEF_1,
    KSEF_2,
    _metadata_json,
    _split,
    _zip,
)
from tests.unit.test_targz_exported_invoices import _package, _tar

BINARY_ARCHIVE = bytes([0xFF, 0x00, 0x41, 0xFB, 0x00, 0x00, 0xFF, 0x2F, 0x3D])
URL_1 = "https://ksef.example/part-1?sig=SENTINEL-ONE"
URL_2 = "https://ksef.example/part-2?sig=SENTINEL-TWO"
EXPIRES = datetime(2030, 1, 1, tzinfo=UTC)


def _part(ordinal: int, url: str) -> PackagePart:
    return PackagePart(
        ordinal_number=ordinal,
        part_name=f"package-{ordinal}.zip",
        method="GET",
        url=url,
        part_size=1024 + ordinal,
        part_hash=f"hash-{ordinal}",
        encrypted_part_size=2048 + ordinal,
        encrypted_part_hash=f"encrypted-{ordinal}",
        expiration_date=EXPIRES,
    )


def _full_package(payload: bytes) -> InvoicePackage:
    return InvoicePackage(
        compression_type="zip",
        invoice_count=2,
        size=len(payload),
        parts=[_part(1, URL_1), _part(2, URL_2)],
        is_truncated=True,
        last_issue_date=date(2026, 1, 2),
        last_invoicing_date=datetime(2026, 1, 2, 10, tzinfo=UTC),
        last_permanent_storage_date=datetime(2026, 1, 2, 11, tzinfo=UTC),
        permanent_storage_hwm_date=datetime(2026, 1, 2, 12, tzinfo=UTC),
    )


def _real_metadata(
    factory: BaseFactory[spec.QueryInvoicesMetadataResponse],
) -> tuple[bytes, list[InvoiceMetadata]]:
    """Read a valid ``_metadata.json`` archive back through the public result."""
    payload, _ = _metadata_json(factory)
    archive = _zip({f"{KSEF_1}.xml": b"<one />", "_metadata.json": payload})
    metadata = ExportedInvoices([archive]).metadata
    assert metadata is not None
    return archive, metadata


def _written(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


class TestArchiveSerialization:
    def test_binary_archive_json_round_trip(self) -> None:
        data = ExportedInvoicesData(archive=BINARY_ARCHIVE)

        ordinary = json.loads(data.model_dump_json())
        sensitive = json.loads(data.to_sensitive_json())
        literal = ordinary["archive"]
        restored = ExportedInvoicesData.model_validate_json(data.to_sensitive_json())

        assert literal == sensitive["archive"]
        assert literal == "_wBB-wAA_y89"
        assert base64.urlsafe_b64decode(literal + "=" * (-len(literal) % 4)) == (
            BINARY_ARCHIVE
        )
        assert restored.archive == BINARY_ARCHIVE
        assert ExportedInvoicesData.model_validate_json(data.model_dump_json()) == data
        assert repr(data) == "ExportedInvoicesData(package=None, metadata=None)"

    @pytest.mark.parametrize(
        ("archive", "literal"),
        [
            (b"", ""),
            (b"a", "YQ=="),
            (b"ab", "YWI="),
            (b"abc", "YWJj"),
            (b"\xff", "_w=="),
            (b"\xfb\xff", "-_8="),
            (b"\xfb\xff\xef\xbe", "-__vvg=="),
        ],
    )
    def test_archive_json_uses_padded_urlsafe_base64(
        self, archive: bytes, literal: str
    ) -> None:
        """Every length modulo three serializes to one fixed URL-safe spelling."""
        data = ExportedInvoicesData(archive=archive)

        assert json.loads(data.model_dump_json())["archive"] == literal
        assert json.loads(data.to_sensitive_json())["archive"] == literal
        assert "+" not in literal
        assert "/" not in literal
        assert len(literal) % 4 == 0

        assert (
            ExportedInvoicesData.model_validate_json(data.model_dump_json()).archive
            == archive
        )
        assert (
            ExportedInvoicesData.model_validate(data.to_sensitive_dict()).archive
            == archive
        )

    @pytest.mark.parametrize(
        ("text", "archive"),
        [
            ("YQ==", b"a"),
            ("YQ", b"a"),
            ("_w==", b"\xff"),
            ("_w", b"\xff"),
            ("/w==", b"\xff"),
        ],
    )
    def test_archive_json_accepts_supported_base64_spellings(
        self, text: str, archive: bytes
    ) -> None:
        """Validation stays lenient; only the serialized spelling is fixed."""
        data = ExportedInvoicesData.model_validate_json(json.dumps({"archive": text}))

        assert data.archive == archive
        assert json.loads(data.model_dump_json())["archive"] == (
            base64.urlsafe_b64encode(archive).decode()
        )

    def test_empty_archive_round_trips_as_empty_bytes(self) -> None:
        data = ExportedInvoicesData(archive=b"")

        assert json.loads(data.to_sensitive_json())["archive"] == ""
        assert (
            ExportedInvoicesData.model_validate_json(data.to_sensitive_json()) == data
        )
        assert ExportedInvoices.from_model(data).archive == b""


class TestPackageFidelity:
    def test_full_package_sensitive_json_round_trip(
        self, inv_query_metadata_resp: BaseFactory[spec.QueryInvoicesMetadataResponse]
    ) -> None:
        archive, metadata = _real_metadata(inv_query_metadata_resp)
        data = ExportedInvoicesData(
            archive=archive, package=_full_package(archive), metadata=metadata
        )

        restored = ExportedInvoicesData.model_validate_json(data.to_sensitive_json())

        assert restored == data
        assert restored.archive == archive
        assert restored.metadata == metadata
        assert restored.package is not None
        assert [part.url for part in restored.package.parts] == [URL_1, URL_2]

    @pytest.mark.parametrize(
        "view",
        [
            pytest.param(lambda data: repr(data), id="repr"),
            pytest.param(lambda data: str(data.model_dump()), id="model-dump"),
            pytest.param(
                lambda data: str(data.model_dump(mode="json")),
                id="model-dump-json-mode",
            ),
            pytest.param(lambda data: data.model_dump_json(), id="model-dump-json"),
        ],
    )
    def test_generic_views_keep_the_presigned_urls_out(
        self,
        view: Callable[[ExportedInvoicesData], str],
        inv_query_metadata_resp: BaseFactory[spec.QueryInvoicesMetadataResponse],
    ) -> None:
        archive, metadata = _real_metadata(inv_query_metadata_resp)
        data = ExportedInvoicesData(
            archive=archive, package=_full_package(archive), metadata=metadata
        )

        dumped = view(data)

        assert "SENTINEL" not in dumped
        assert "package-1.zip" in dumped

    def test_generic_package_dump_cannot_be_validated_back(
        self, inv_query_metadata_resp: BaseFactory[spec.QueryInvoicesMetadataResponse]
    ) -> None:
        archive, metadata = _real_metadata(inv_query_metadata_resp)
        data = ExportedInvoicesData(
            archive=archive, package=_full_package(archive), metadata=metadata
        )

        with pytest.raises(ValidationError, match="url"):
            _ = ExportedInvoicesData.model_validate(data.model_dump(mode="json"))

        assert ExportedInvoicesData.model_validate(data.to_sensitive_dict()) == data


class TestSchema:
    def test_data_schema_is_json_serializable(self) -> None:
        validation = ExportedInvoicesData.model_json_schema()
        serialization = ExportedInvoicesData.model_json_schema(mode="serialization")
        schema_text = json.dumps(validation)

        assert validation["properties"]["archive"] == {
            "title": "Archive",
            "type": "string",
            "format": "base64url",
        }
        assert validation["required"] == ["archive"]
        assert validation["properties"]["package"]["anyOf"][0]["$ref"] == (
            "#/$defs/InvoicePackage"
        )
        assert validation["properties"]["metadata"]["anyOf"][0]["items"]["$ref"] == (
            "#/$defs/InvoiceMetadata"
        )
        assert "url" in validation["$defs"]["PackagePart"]["properties"]
        assert "url" not in serialization["$defs"]["PackagePart"]["properties"]
        assert "presigned URL" in schema_text

    def test_facade_exports_the_data_model(self) -> None:
        assert "ExportedInvoicesData" in ksef2.models.__all__
        assert ksef2.models.ExportedInvoicesData is ExportedInvoicesData
        assert ExportedInvoicesData.__module__ == "ksef2._domain.models.invoices"
        assert ksef2.clients.ExportedInvoices is ExportedInvoices


class TestSnapshotRoundTrip:
    @pytest.mark.parametrize("kind", ["zip", "tar_gz"])
    def test_snapshot_round_trip_preserves_export_behavior(
        self,
        kind: str,
        inv_query_metadata_resp: BaseFactory[spec.QueryInvoicesMetadataResponse],
        tmp_path: Path,
    ) -> None:
        payload, _ = _metadata_json(inv_query_metadata_resp)
        if kind == "zip":
            parts = _split(
                _zip(
                    {
                        f"{KSEF_1}.xml": b"<one />",
                        f"{KSEF_2}.xml": b"<two />",
                        "_metadata.json": payload,
                    }
                ),
                3,
            )
            exported = ExportedInvoices(parts)
        else:
            tar_archive = _tar(
                [
                    (tarfile.TarInfo(f"{KSEF_1}.xml"), b"<one />"),
                    (tarfile.TarInfo(f"{KSEF_2}.xml"), b"<two />"),
                    (tarfile.TarInfo("_metadata.json"), payload),
                ]
            )
            exported = _package(tar_archive)

        data = exported.to_model()
        restored = ExportedInvoices.from_model(
            ExportedInvoicesData.model_validate_json(data.to_sensitive_json())
        )

        original_dir = tmp_path / "original"
        restored_dir = tmp_path / "restored"
        _ = exported.save(original_dir)
        _ = restored.save(restored_dir)

        assert data.archive == exported.archive
        assert data.package == exported.package
        assert data.metadata == exported.metadata
        assert restored.archive == exported.archive
        assert restored.package == exported.package
        assert restored.metadata == exported.metadata
        assert list(restored.invoices()) == list(exported.invoices())
        assert _written(restored_dir) == _written(original_dir)
        assert (restored_dir / f"{KSEF_1}.xml").read_bytes() == b"<one />"
        assert (restored_dir / "_metadata.json").read_bytes() == payload

    def test_empty_and_missing_metadata_round_trip(self) -> None:
        empty = ExportedInvoices([]).to_model()
        no_metadata_file = ExportedInvoices([_zip({f"{KSEF_1}.xml": b"<one />"})])
        empty_metadata_list = ExportedInvoices(
            [_zip({"_metadata.json": b'{"invoices": []}'})]
        )

        assert empty.metadata is None
        assert empty_metadata_list.to_model().metadata == []
        assert no_metadata_file.to_model().metadata is None
        assert ExportedInvoices.from_model(empty).metadata is None
        assert (
            ExportedInvoices.from_model(empty_metadata_list.to_model()).metadata == []
        )
        assert ExportedInvoices.from_model(no_metadata_file.to_model()).metadata is None


class TestMetadataConversion:
    def test_to_model_materializes_metadata_and_preserves_errors(self) -> None:
        invalid_metadata = ExportedInvoices(
            [_zip({"_metadata.json": b'{"invoices": [{}]}'})]
        )
        malformed_archive = ExportedInvoices([b"not an archive"])

        with pytest.raises(KSeFValidationError, match="_metadata.json"):
            _ = invalid_metadata.to_model()
        with pytest.raises(zipfile.BadZipFile):
            _ = malformed_archive.to_model()

    def test_constructor_stays_lazy_until_metadata_is_read(self) -> None:
        unreadable = ExportedInvoices([b"not an archive"])
        exported = ExportedInvoices([_zip({"_metadata.json": b"not json"})])

        assert unreadable.package is None
        with pytest.raises(zipfile.BadZipFile):
            _ = unreadable.metadata
        with pytest.raises(KSeFValidationError, match="_metadata.json"):
            _ = exported.to_model()

    def test_from_model_uses_the_supplied_metadata(
        self, inv_query_metadata_resp: BaseFactory[spec.QueryInvoicesMetadataResponse]
    ) -> None:
        archive, metadata = _real_metadata(inv_query_metadata_resp)
        hostile_archive = _zip(
            {f"{KSEF_1}.xml": b"<one />", "_metadata.json": b'{"invoices": [{}]}'}
        )

        seeded = ExportedInvoices.from_model(
            ExportedInvoicesData(archive=hostile_archive, metadata=metadata)
        )
        absent = ExportedInvoices.from_model(
            ExportedInvoicesData(archive=hostile_archive)
        )

        assert seeded.metadata == metadata
        assert seeded.metadata is not metadata
        assert absent.metadata is None
        assert seeded.to_model().metadata == metadata

    def test_conversions_do_not_alias_mutable_models(
        self, inv_query_metadata_resp: BaseFactory[spec.QueryInvoicesMetadataResponse]
    ) -> None:
        archive, _ = _real_metadata(inv_query_metadata_resp)
        exported = ExportedInvoices([archive])
        data = exported.to_model()

        assert data.metadata is not None
        assert data.metadata is not exported.metadata
        data.metadata[0].invoice_number = "mutated-in-snapshot"
        assert exported.metadata is not None
        assert exported.metadata[0].invoice_number != "mutated-in-snapshot"
        assert exported.metadata is exported.metadata

        rebuilt = ExportedInvoices.from_model(data)
        assert rebuilt.metadata is not None
        assert rebuilt.metadata is not data.metadata
        assert rebuilt.metadata[0].invoice_number == "mutated-in-snapshot"
        rebuilt.metadata[0].invoice_number = "mutated-in-rebuilt"
        assert data.metadata[0].invoice_number == "mutated-in-snapshot"
        assert rebuilt.metadata is rebuilt.metadata

    def test_conversions_do_not_alias_the_package(
        self, inv_query_metadata_resp: BaseFactory[spec.QueryInvoicesMetadataResponse]
    ) -> None:
        archive, _ = _real_metadata(inv_query_metadata_resp)
        package = _full_package(archive)
        exported = ExportedInvoices([archive], package=package)

        data = exported.to_model()
        assert data.package is not None
        data.package.invoice_count = 99
        data.package.parts[0].part_name = "mutated.zip"
        assert exported.package is not None
        assert exported.package.invoice_count == package.invoice_count
        assert exported.package.parts[0].part_name == "package-1.zip"

        rebuilt = ExportedInvoices.from_model(data)
        assert rebuilt.package is not None
        rebuilt.package.invoice_count = 7
        assert data.package.invoice_count == 99


class TestRestoredArchiveSafety:
    @pytest.mark.parametrize("entry", ["../evil.xml", "a/../../evil.xml"])
    def test_restored_zip_still_refuses_traversal(
        self, entry: str, tmp_path: Path
    ) -> None:
        archive = _zip({f"{KSEF_1}.xml": b"<ok />", entry: b"<evil />"})
        restored = ExportedInvoices.from_model(
            ExportedInvoicesData(archive=archive, metadata=None)
        )
        target = tmp_path / "out"

        with pytest.raises(ValueError, match="Unsafe archive entry path"):
            _ = restored.save(target)

        assert not target.exists()
        assert not (tmp_path / "evil.xml").exists()

    def test_restored_zip_still_refuses_symlink_entries(self, tmp_path: Path) -> None:
        buffer = io.BytesIO()
        member = zipfile.ZipInfo("link.xml")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("good.xml", b"<ok />")
            archive.writestr(member, b"../outside")
        restored = ExportedInvoices.from_model(
            ExportedInvoicesData(archive=buffer.getvalue(), metadata=None)
        )
        target = tmp_path / "out"

        with pytest.raises(ValueError, match="Unsafe archive entry type"):
            _ = restored.save(target)

        assert not target.exists()

    @pytest.mark.parametrize("entry", ["../evil.xml", "/evil.xml"])
    def test_restored_targz_still_refuses_traversal(
        self, entry: str, tmp_path: Path
    ) -> None:
        archive = _tar(
            [(tarfile.TarInfo("good.xml"), b"<ok />"), (tarfile.TarInfo(entry), b"bad")]
        )
        restored = ExportedInvoices.from_model(
            ExportedInvoicesData(
                archive=archive, package=_package(archive).package, metadata=None
            )
        )
        target = tmp_path / "out"

        with pytest.raises(ValueError, match="Unsafe archive entry path"):
            _ = restored.save(target)

        assert not target.exists()

    def test_restored_targz_still_refuses_links(self, tmp_path: Path) -> None:
        member = tarfile.TarInfo("evil.xml")
        member.type = tarfile.SYMTYPE
        member.linkname = "good.xml"
        archive = _tar([(tarfile.TarInfo("good.xml"), b"<ok />"), (member, b"")])
        restored = ExportedInvoices.from_model(
            ExportedInvoicesData(
                archive=archive, package=_package(archive).package, metadata=None
            )
        )
        target = tmp_path / "out"

        with pytest.raises(ValueError, match="Unsafe archive entry type"):
            _ = restored.save(target)

        assert not target.exists()
