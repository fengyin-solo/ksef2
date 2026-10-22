import io
import zipfile

from ksef2._core.packages import PackageInvoice, PackageReader


def _archive(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_reader_yields_every_invoice_xml_in_an_archive() -> None:
    archive = _archive(
        {
            "invoice-1.xml": b"<one/>",
            "nested/invoice-2.XML": b"<two/>",
        }
    )

    invoices = list(PackageReader(archive).invoices())

    assert invoices == [
        PackageInvoice(name="invoice-1.xml", xml=b"<one/>"),
        PackageInvoice(name="nested/invoice-2.XML", xml=b"<two/>"),
    ]


def test_reader_skips_known_metadata_and_non_xml_entries() -> None:
    archive = _archive(
        {
            "manifest.xml": b"<manifest/>",
            "folder/Metadata.XML": b"<metadata/>",
            "signature.xml": b"<signature/>",
            "readme.txt": b"not xml",
            "invoice.xml": b"<invoice/>",
        }
    )

    invoices = list(PackageReader(archive))

    assert [invoice.name for invoice in invoices] == ["invoice.xml"]


def test_reader_reads_invoices_across_several_parts_in_order() -> None:
    first = _archive({"a.xml": b"<a/>"})
    second = _archive({"b.xml": b"<b/>"})

    invoices = list(PackageReader([first, second]))

    assert [invoice.name for invoice in invoices] == ["a.xml", "b.xml"]


def test_reader_of_an_empty_part_list_yields_nothing() -> None:
    assert list(PackageReader([])) == []
