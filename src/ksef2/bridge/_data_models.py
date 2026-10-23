"""Data model of the decrypted invoice export returned by ``ExportJob.wait()``.

``ksef2.clients.ExportedInvoices`` is a live object that opens an archive lazily.
The manifest describes it by data instead, and that data is exactly what the
object holds: the archive bytes and whatever the archive or its status reported.
"""

from pydantic import BaseModel, Field

from ksef2._domain.models.invoices import InvoiceMetadata, InvoicePackage


class ExportedInvoices(BaseModel):
    """Decrypted invoice export, as data.

    Attributes:
        archive: Decrypted package parts joined into one ZIP or TarGz archive, with one ``<ksef_number>.xml`` file per invoice and a ``_metadata.json`` file. An export that matched no invoices has an empty archive.
        package: Package status from the export that produced this archive, when that status is known. It is not read back from a saved archive.
        metadata: ``invoices`` list of the archive's ``_metadata.json``, or ``None`` when the archive carries no such file.
    """

    archive: bytes = Field(
        description=(
            "ZIP or TarGz archive of the export. Persist these bytes and reopen"
            " them with `ExportedInvoices.from_archive()`."
        )
    )
    package: InvoicePackage | None = None
    metadata: list[InvoiceMetadata] | None = None
