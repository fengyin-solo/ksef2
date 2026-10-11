---
title: Migrate to ksef2 1.0
description: Replace deprecated imports and invoice workflows while existing code keeps working through 1.x.
---

Existing import paths and deprecated method names keep working throughout 1.x.
They emit `DeprecationWarning` naming the replacement. Removal may happen no
earlier than 2.0.0, and is still a decision for that release. New code should
use the public facades and operation handles below.

## Imports

Before, these are the imports used by existing applications:

```python
from ksef2.core.exceptions import KSeFApiError
from ksef2.core.xades import load_certificate_from_pem
from ksef2.domain.models.invoices import InvoicesFilter
from ksef2.domain.models.pagination import InvoiceMetadataParams
from ksef2.domain.models.session import FormSchema
from ksef2.services.invoices import InvoicesFilter
from ksef2.services.builders import FA3InvoiceBuilder
from ksef2.services.renderers.xslt import InvoiceXSLTRenderer
```

After, the same types and helpers come from the supported facades:

```python
from ksef2 import FormSchema, KSeFApiError
from ksef2.models import InvoicesFilter, InvoiceMetadataParams
from ksef2.xades import load_certificate_from_pem
from ksef2.fa3 import FA3InvoiceBuilder
from ksef2.renderers import InvoiceXSLTRenderer
```

| Old path | Migration |
| --- | --- |
| `ksef2.domain.models` and its submodules | `ksef2.models`, or `ksef2.fa3` for FA(3) domain models |
| `ksef2.infra.mappers` | `ksef2.raw.mappers` |
| `ksef2.infra.schema.api.spec` / `.supp` | `from ksef2.raw import spec, supp` |
| `ksef2.infra.schema.fa3` and generated submodules | Keep the deprecated alias if generated XSD classes or schema resources are required. There is no public replacement for every generated FA(3) class. For invoice construction, use `ksef2.fa3.FA3InvoiceBuilder`. |
| `ksef2.services.builders` | `ksef2.fa3` |
| `ksef2.services.renderers.xslt` | `ksef2.renderers` |
| `ksef2.clients.base` and other client implementation modules | `ksef2.clients` |
| `ksef2.config` | `ksef2` |
| `ksef2.endpoints` | `ksef2.raw` |
| `ksef2.logging` | Application-owned standard logging or structlog configuration; the alias remains available for existing helpers. |

Aliases reuse the canonical modules and classes. They do not load the optional
PDF renderer until it is requested.

## Send, wait and download UPO

These snippets assume an open online `session` and invoice XML in `invoice_xml`.
Before, polling and UPO download use separate calls with the reference:

```python
response = session.send_invoice(invoice_xml=invoice_xml)
status = session.wait_for_invoice_ready(
    invoice_reference_number=response.reference_number,
    timeout=120.0,
)
upo = session.get_invoice_upo_by_reference(
    invoice_reference_number=response.reference_number,
)
# Alternatively: status = session.send_invoice_and_wait(invoice_xml=invoice_xml)
```

After, retain the submission and use it for both operations:

```python
submission = session.send_invoice(invoice_xml)
status = submission.wait(timeout=120.0)
upo = submission.download_upo()
```

If only a stored reference is available, use
`session.download_invoice_upo(reference_number=reference)` for the UPO.
`wait_for_invoice_ready()` remains supported for existing reference-based polling.

For async code, await each operation separately:

```python
submission = await session.send_invoice(invoice_xml)
status = await submission.wait(timeout=120.0)
upo = await submission.download_upo()
```

## Search, download and export

Assume `auth` is authenticated and `filters` is an `InvoicesFilter`.
Before:

```python
page = auth.invoices.query_metadata(filters=filters, params=params)
for invoice in auth.invoices.all_metadata(filters=filters, params=params):
    xml = auth.invoices.download_invoice(ksef_number=invoice.ksef_number)
for page_items in auth.invoices.query_metadata_pages(filters=filters, params=params):
    print(page_items)
parts = auth.invoices.export_and_download(filters=filters)
archive = b"".join(parts)
```

After:

```python
pager = auth.invoices.search(filters, params=params)
page = pager.first_page()
for invoice in auth.invoices.search(filters, params=params):
    xml = auth.invoices.download(invoice.ksef_number)
for page_items in auth.invoices.search(filters, params=params).pages():
    print(page_items)
exported = auth.invoices.export(filters=filters).wait()
archive = exported.archive
```

`query_metadata()` returns an `QueryInvoicesMetadataResponse`, while `first_page()` returns
its list of invoices. Paging flags stay on the deprecated page response if your
application still needs them. Search is lazy and requests data when consumed.
In async code, use `async for`, await `first_page()` and `download()`, and use
`job = await auth.invoices.export(filters=filters)` followed by
`exported = await job.wait()`.

## Find deprecated uses

Python usually hides `DeprecationWarning` in imported application modules.
Run tests with `python -W default::DeprecationWarning -m pytest` to list uses,
or `python -W error::DeprecationWarning -m pytest` to require migration.
Method aliases also carry PEP 702 deprecation markers for IDEs and type checkers.
An import warning occurs when the alias is first loaded, not on every cached import.
