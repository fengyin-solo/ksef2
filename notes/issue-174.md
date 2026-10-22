# Issue 174 verification

Public APIs added: `ksef2.fa3.parse_invoice_xml(bytes) -> KsefInvoice`,
`ksef2.renderers.PDFPageSize`, and PDF exporter keywords `page_size`,
`verification_environment`, and per-export `ksef_number`.

## Four reports against 0.17.0

A `git archive v0.17.0` checkout was run with the current Python 3.12 dependencies
and beartype installed. A public-builder probe reproduced each report:

| Report | 0.17.0 runtime result | Result in this PR |
| --- | --- | --- |
| Rowless KOR_ZAL | `At least one invoice line or order is required` | Fixed; public builder output passes XSD validation and parses back with no rows and the supplied total. |
| Rowless KOR_ROZ | Same validation failure | Fixed with the same public build/XML/parse checks. |
| Excise return | Model value `True`, but no `ZwrotAkcyzy` in XML | Fixed; `True` emits `1`, false/absent omit the optional marker. |
| Transport-only annotations | `Annotation details are empty` from `done()` | Already fixed in the starting branch; existing behavioral tests pass. |

The old paths are `src/ksef2/domain/models/fa3/body/root.py`,
`src/ksef2/infra/mappers/invoices/fa3/domain/invoice.py`, and
`src/ksef2/services/builders/fa3/sub/annotations.py`. The current paths have a
leading underscore on `domain`, `infra`, and `services`.

## Verification

- `uv run --all-groups --extra pdf --extra runtime-checks pytest tests/unit/ tests/e2e/mappers/fa3/ -q`: 2,422 passed.
- Same dependencies, `pytest tests/integration/builders/fa3/ -m integration -q`: 38 passed. These are local builder/XSD contracts, not network tests.
- `KSEF2_RUNTIME_CHECKS=1`, unit suite: 2,381 passed, 3 skipped.
- Focused parse/PDF/annotations tests with runtime checks: 45 passed.
- Ruff check and format check, source basedpyright at warning threshold, test basedpyright at error threshold, docs Markdown/path/example validation, and `uv build`: passed. Existing test typing warnings are outside the error threshold.
- Generated real A4 portrait and landscape PDFs with WeasyPrint, inspected page dimensions using PyMuPDF, decoded each verification QR independently using zxing-cpp, and extracted the assigned-number label. Dimensions and URL matched. On this Mac the native libraries required `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`.

Falsification [R45: Falsify Changed Tests]: temporarily restored the row validator,
removed the excise mapping and transport-state emptiness checks, disabled parser
namespace/DTD guards, and changed the QR hash to stripped XML. The focused suite
reported 11 failures naming those behaviors. A separate mutation that removed the
page-size CSS produced six failures, one per supported paper/orientation choice.
All mutations were restored before the passing runs.

## Limits and exclusions

Parsing applies domain validation, not full XSD validation, and is not lossless.
Original XML bytes must be retained for a verification hash. The QR uses the
Ministry's KOD I format from https://github.com/CIRFMF/ksef-docs/blob/main/kody-qr.md.
It supports assigned KSeF numbers, with explicit TEST/DEMO selection and production
as default. It does not check remote acceptance or whether the supplied number
belongs to the document. Offline certificate QR signing and replacing consumers'
custom layouts are excluded. No live KSeF requests were needed or run.

## Proposed rule update

[R23: Maintain The Rules] Add to the rendering workflow rules: "Derive invoice
verification hashes from the exact original XML bytes. Parsing, normalization,
whitespace removal, and rebuilding must never precede hashing. Verify the rendered
QR with an independent decoder when changing its encoding or layout."
