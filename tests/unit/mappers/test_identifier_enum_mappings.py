import pytest

from ksef2._infra.mappers.certificates.responses import from_spec
from ksef2._infra.mappers.permissions.requests.grants import (
    indirect_subject_identifier_from_literal,
)
from ksef2._infra.mappers.permissions.requests.shared import (
    cert_subject_identifier_from_literal,
    indirect_target_identifier_from_literal,
)
from ksef2._infra.mappers.permissions.responses.query_entity import (
    authorization_author_identifier_from_spec,
)
from ksef2._infra.schema.api import spec


@pytest.mark.parametrize(
    ("literal", "certificate", "author", "subject"),
    [
        (
            "nip",
            spec.CertificateSubjectIdentifierType.Nip,
            spec.EntityAuthorizationsAuthorIdentifierType.Nip,
            spec.IndirectPermissionsSubjectIdentifierType.Nip,
        ),
        (
            "pesel",
            spec.CertificateSubjectIdentifierType.Pesel,
            spec.EntityAuthorizationsAuthorIdentifierType.Pesel,
            spec.IndirectPermissionsSubjectIdentifierType.Pesel,
        ),
        (
            "fingerprint",
            spec.CertificateSubjectIdentifierType.Fingerprint,
            spec.EntityAuthorizationsAuthorIdentifierType.Fingerprint,
            spec.IndirectPermissionsSubjectIdentifierType.Fingerprint,
        ),
    ],
)
def test_subject_identifier_mappings(
    literal: str,
    certificate: spec.CertificateSubjectIdentifierType,
    author: spec.EntityAuthorizationsAuthorIdentifierType,
    subject: spec.IndirectPermissionsSubjectIdentifierType,
) -> None:
    assert from_spec(certificate) == literal
    assert cert_subject_identifier_from_literal(literal) == certificate
    assert authorization_author_identifier_from_spec(author) == literal
    assert indirect_subject_identifier_from_literal(literal) == subject


@pytest.mark.parametrize(
    ("literal", "expected"),
    [
        ("nip", spec.IndirectPermissionsTargetIdentifierType.Nip),
        ("all_partners", spec.IndirectPermissionsTargetIdentifierType.AllPartners),
        ("internal_id", spec.IndirectPermissionsTargetIdentifierType.InternalId),
    ],
)
def test_indirect_target_identifier_mappings(
    literal: str, expected: spec.IndirectPermissionsTargetIdentifierType
) -> None:
    assert indirect_target_identifier_from_literal(literal) == expected
