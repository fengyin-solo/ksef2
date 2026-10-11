"""Application imports survive the 1.0 rename with canonical type identity."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    ("legacy", "canonical", "replacement"),
    [
        ("core.exceptions", "_core.exceptions", "ksef2"),
        ("core.xades", "_core.xades", "ksef2.xades"),
        ("domain.models", "_domain.models", "ksef2.models"),
        ("domain.models.invoices", "_domain.models.invoices", "ksef2.models"),
        ("domain.models.pagination", "_domain.models.pagination", "ksef2.models"),
        ("domain.models.session", "_domain.models.session", "ksef2.models"),
        ("domain.models.fa3.body.row", "_domain.models.fa3.body.row", "ksef2.fa3"),
        ("infra.mappers", "_infra.mappers", "ksef2.raw.mappers"),
        ("infra.mappers.invoices", "_infra.mappers.invoices", "ksef2.raw.mappers"),
        ("infra.schema", "_infra.schema", "ksef2.raw"),
        ("infra.schema.fa3", "_infra.schema.fa3", "ksef2.fa3"),
        ("infra.schema.fa3.models", "_infra.schema.fa3.models", "ksef2.fa3"),
        (
            "infra.schema.fa3.models.schemat",
            "_infra.schema.fa3.models.schemat",
            "ksef2.fa3",
        ),
        (
            "infra.schema.api.spec.models",
            "_infra.schema.api.spec.models",
            "ksef2.raw.spec",
        ),
        ("services.invoices", "_services.invoices", "ksef2.clients"),
        ("services.async_invoices", "_services.async_invoices", "ksef2.clients"),
        ("services.builders", "_services.builders", "ksef2.fa3"),
        ("services.builders.fa3.root", "_services.builders.fa3.root", "ksef2.fa3"),
        ("services.renderers.xslt", "_services.renderers.xslt", "ksef2.renderers"),
        ("clients.base", "_clients.base", "ksef2.clients"),
        ("clients.async_online", "_clients.async_online", "ksef2.clients"),
        ("endpoints.invoices", "_endpoints.invoices", "ksef2.raw"),
        ("config", "_config", "ksef2"),
        ("logging", "_logging", "standard logging"),
    ],
)
def test_legacy_import_warns_and_reuses_canonical_module(
    legacy: str, canonical: str, replacement: str
) -> None:
    # A fresh interpreter exercises the first import without clearing shared modules.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import importlib
import warnings
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter('always', DeprecationWarning)
    old = importlib.import_module('ksef2.{legacy}')
new = importlib.import_module('ksef2.{canonical}')
assert old is new
messages = [str(w.message) for w in caught if w.category is DeprecationWarning]
matching = [m for m in messages if m.startswith('`ksef2.{legacy}` is deprecated')]
assert len(matching) == 1, messages
assert {replacement!r} in matching[0], matching
assert 'no earlier than ksef2 2.0.0' in matching[0], matching
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter('always', DeprecationWarning)
    assert importlib.import_module('ksef2.{legacy}') is new
assert not caught
""",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_real_application_import_forms_and_resources() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-W",
            "ignore::DeprecationWarning",
            "-c",
            """
import sys
import ksef2
assert 'ksef2._services.renderers.pdf' not in sys.modules
from ksef2.domain.models.invoices import InvoicesFilter
from ksef2.domain.models.pagination import InvoiceMetadataParams
from ksef2.domain.models.session import FormSchema
from ksef2.services.invoices import InvoicesFilter as ServiceFilter
from ksef2.core.exceptions import KSeFApiError
from ksef2.core.xades import load_certificate_from_pem
from ksef2.services.builders import FA3InvoiceBuilder
from ksef2.services.renderers.xslt import InvoiceXSLTRenderer
import ksef2.infra.schema.fa3.models.schemat
from ksef2.infra.schema.fa3 import STYLESHEET_PATH
from ksef2 import models, fa3, xades, renderers
assert InvoicesFilter is ServiceFilter is models.InvoicesFilter
assert InvoiceMetadataParams is models.InvoiceMetadataParams
assert FormSchema is ksef2.FormSchema
assert KSeFApiError is ksef2.KSeFApiError
assert load_certificate_from_pem is xades.load_certificate_from_pem
assert FA3InvoiceBuilder is fa3.FA3InvoiceBuilder
assert InvoiceXSLTRenderer is renderers.InvoiceXSLTRenderer
assert STYLESHEET_PATH.is_file()
assert ksef2.infra.schema.fa3.models.schemat is sys.modules['ksef2._infra.schema.fa3.models.schemat']
""",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
