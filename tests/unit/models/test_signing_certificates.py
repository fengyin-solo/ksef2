"""Signing-certificate records: identity, metadata derived from the certificate, secrecy."""

import copy
import datetime
import hashlib
import os
import pickle

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import ValidationError
import pytest

from ksef2._config import Environment
from ksef2._core.exceptions import KSeFArgumentError, KSeFValidationError
from ksef2._domain.models.signing_certificates import (
    SigningCertificate,
    SigningCertificateInfo,
    SigningCertificateRef,
)
from ksef2._domain.models.xades import XAdESCredentials
from tests.unit.support import xades_material as material
from tests.unit.support.xades_material import TestKey

requires_unchecked_types = pytest.mark.skipif(
    bool(os.environ.get("KSEF2_RUNTIME_CHECKS")),
    reason="beartype rejects the out-of-contract value before the guard runs",
)

PASSWORD = b"store-test-password"
NOW = datetime.datetime(2026, 5, 1, 12, 0, tzinfo=datetime.UTC)


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def ec_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _fingerprint(certificate: x509.Certificate) -> str:
    return hashlib.sha256(certificate.public_bytes(Encoding.DER)).hexdigest()


def _public_key_fingerprint(certificate: x509.Certificate) -> str:
    return hashlib.sha256(
        certificate.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo
        )
    ).hexdigest()


@pytest.fixture(params=["rsa", "ec"])
def pair(request: pytest.FixtureRequest) -> tuple[x509.Certificate, TestKey]:
    """Return a self-signed certificate with the private key it was issued for."""
    key: TestKey = request.getfixturevalue(f"{request.param}_key")
    return material.self_signed(key, common_name=f"ksef2 {request.param}"), key


class TestInfoDerivedFromTheCertificate:
    def test_metadata_describes_the_certificate_exactly(
        self, pair: tuple[x509.Certificate, TestKey]
    ) -> None:
        certificate, key = pair
        record = SigningCertificate(
            XAdESCredentials(certificate, key),
            environment=Environment.TEST,
        )

        assert record.info.reference.fingerprint_sha256 == _fingerprint(certificate)
        assert record.info.public_key_sha256 == _public_key_fingerprint(certificate)
        assert record.info.x509_serial_number == certificate.serial_number
        assert record.info.valid_from == certificate.not_valid_before_utc
        assert record.info.valid_to == certificate.not_valid_after_utc
        assert record.info.valid_from.tzinfo is not None
        assert record.info.valid_to.tzinfo is not None
        assert record.reference == record.info.reference

    @pytest.mark.parametrize("credential_format", ["pem", "der", "pkcs12"])
    @pytest.mark.parametrize("password", [None, PASSWORD])
    def test_the_same_pair_describes_itself_the_same_way_whatever_its_input_format(
        self,
        rsa_key: rsa.RSAPrivateKey,
        credential_format: material.CredentialFormat,
        password: bytes | None,
    ) -> None:
        certificate = material.self_signed(rsa_key, common_name="ksef2 formats")
        expected = SigningCertificate(
            XAdESCredentials(certificate, rsa_key),
            environment=Environment.DEMO,
            certificate_type="authentication",
            ksef_serial_number="0123456789ABCDEF",
        ).info

        credentials = material.build_credentials(
            certificate, rsa_key, credential_format, password=password
        )
        record = SigningCertificate(
            credentials,
            environment=Environment.DEMO,
            certificate_type="authentication",
            ksef_serial_number="0123456789ABCDEF",
        )

        assert record.info == expected

    def test_an_expired_or_not_yet_valid_pair_is_still_a_valid_record(
        self, rsa_key: rsa.RSAPrivateKey
    ) -> None:
        expired = material.self_signed_with_validity(
            rsa_key,
            not_valid_before=NOW - datetime.timedelta(days=365),
            not_valid_after=NOW - datetime.timedelta(days=30),
        )
        not_yet_valid = material.self_signed_with_validity(
            rsa_key,
            not_valid_before=NOW + datetime.timedelta(days=30),
            not_valid_after=NOW + datetime.timedelta(days=60),
        )

        for certificate in (expired, not_yet_valid):
            record = SigningCertificate(
                XAdESCredentials(certificate, rsa_key), environment=Environment.TEST
            )
            assert record.info.reference.fingerprint_sha256 == _fingerprint(certificate)

    def test_a_twenty_byte_x509_serial_is_kept_and_ksef_stays_unknown(
        self, rsa_key: rsa.RSAPrivateKey
    ) -> None:
        serial = x509.random_serial_number()
        certificate = material.self_signed(rsa_key, serial_number=serial)

        info = SigningCertificate(
            XAdESCredentials(certificate, rsa_key), environment=Environment.TEST
        ).info

        assert serial.bit_length() > 8 * 16
        assert info.x509_serial_number == serial
        assert info.ksef_serial_number is None

    @pytest.mark.parametrize("certificate_type", [None, "authentication", "offline"])
    def test_the_metadata_carries_the_ksef_fields_it_was_given(
        self, rsa_key: rsa.RSAPrivateKey, certificate_type: str | None
    ) -> None:
        certificate = material.self_signed(rsa_key, common_name="ksef2 kinds")

        record = SigningCertificate(
            XAdESCredentials(certificate, rsa_key),
            environment=Environment.PRODUCTION,
            certificate_type=certificate_type,  # type: ignore[arg-type]
            ksef_serial_number="0123456789ABCDEF",
        )

        assert record.info.certificate_type == certificate_type
        assert record.info.ksef_serial_number == "0123456789ABCDEF"
        assert record.info.reference.environment is Environment.PRODUCTION

    @requires_unchecked_types
    @pytest.mark.parametrize("certificate_type", ["signing", "Authentication"])
    def test_an_unknown_certificate_purpose_is_rejected(
        self, rsa_key: rsa.RSAPrivateKey, certificate_type: str
    ) -> None:
        with pytest.raises(KSeFValidationError, match="certificate_type"):
            SigningCertificate(
                XAdESCredentials(material.self_signed(rsa_key), rsa_key),
                environment=Environment.TEST,
                certificate_type=certificate_type,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize("ksef_serial_number", ["0123456789abcdef", "123", ""])
    def test_a_ksef_serial_number_must_be_sixteen_uppercase_hex_characters(
        self, rsa_key: rsa.RSAPrivateKey, ksef_serial_number: str
    ) -> None:
        with pytest.raises(KSeFValidationError):
            SigningCertificate(
                XAdESCredentials(material.self_signed(rsa_key), rsa_key),
                environment=Environment.TEST,
                ksef_serial_number=ksef_serial_number,
            )

    @requires_unchecked_types
    def test_the_holder_must_be_credentials(self) -> None:
        with pytest.raises(KSeFArgumentError, match="XAdESCredentials holder"):
            SigningCertificate(  # type: ignore[arg-type]
                "cert-and-key", environment=Environment.TEST
            )


class TestReference:
    def test_the_reference_is_hashable_and_equal_by_value(
        self, rsa_key: rsa.RSAPrivateKey
    ) -> None:
        certificate = material.self_signed(rsa_key, common_name="ksef2 identity")
        fingerprint = _fingerprint(certificate)
        reference = SigningCertificateRef.for_certificate(
            certificate, environment=Environment.TEST
        )

        assert reference == SigningCertificateRef(
            environment=Environment.TEST, fingerprint_sha256=fingerprint
        )
        assert hash(reference) == hash(
            SigningCertificateRef(
                environment=Environment.TEST, fingerprint_sha256=fingerprint
            )
        )
        assert {reference: "record"}[
            SigningCertificateRef(
                environment=Environment.TEST, fingerprint_sha256=fingerprint
            )
        ] == "record"
        assert reference != SigningCertificateRef(
            environment=Environment.DEMO, fingerprint_sha256=fingerprint
        )

    @pytest.mark.parametrize(
        "fingerprint",
        [
            "A" * 64,
            "d31219C3825d1f87e3ec15419ca99272e61e3df50850662ef3e60ce9f9711057",
            ":".join(f"{index:02x}" for index in range(32)),
            "a" * 63,
            "a" * 65,
            "",
        ],
    )
    def test_a_fingerprint_must_be_sixty_four_lowercase_hex_characters(
        self, fingerprint: str
    ) -> None:
        with pytest.raises(KSeFValidationError, match="fingerprint_sha256"):
            SigningCertificateRef(
                environment=Environment.TEST, fingerprint_sha256=fingerprint
            )

    def test_the_reference_refuses_fields_it_does_not_know(self) -> None:
        with pytest.raises(KSeFValidationError, match="nip"):
            SigningCertificateRef(
                environment=Environment.TEST,
                fingerprint_sha256="a" * 64,
                nip="5265877635",  # type: ignore[call-arg]
            )


class TestMetadataModel:
    def _info(self, **overrides: object) -> SigningCertificateInfo:
        values: dict[str, object] = {
            "reference": SigningCertificateRef(
                environment=Environment.TEST, fingerprint_sha256="a" * 64
            ),
            "x509_serial_number": 7,
            "public_key_sha256": "b" * 64,
            "valid_from": NOW,
            "valid_to": NOW + datetime.timedelta(days=1),
        }
        values.update(overrides)
        return SigningCertificateInfo.model_validate(values)

    def test_validity_period_must_run_forward(self) -> None:
        with pytest.raises(KSeFValidationError, match="valid_to is before valid_from"):
            self._info(valid_to=NOW - datetime.timedelta(days=1))

    def test_validity_period_has_to_name_its_timezone(self) -> None:
        with pytest.raises(KSeFValidationError, match="timezone info"):
            self._info(valid_from=NOW.replace(tzinfo=None))

    def test_a_negative_x509_serial_is_rejected(self) -> None:
        with pytest.raises(KSeFValidationError, match="x509_serial_number"):
            self._info(x509_serial_number=-1)

    def test_the_dump_round_trips(self) -> None:
        info = self._info(
            certificate_type="offline", ksef_serial_number="0123456789ABCDEF"
        )

        assert SigningCertificateInfo.model_validate(info.model_dump()) == info

    def test_the_record_is_frozen(self) -> None:
        info = self._info()

        # ``__setattr__`` is Pydantic's own, so it reports Pydantic's error here.
        with pytest.raises(ValidationError, match="Instance is frozen"):
            info.x509_serial_number = 9  # type: ignore[misc]


class TestSecrecy:
    @pytest.fixture
    def record(self, rsa_key: rsa.RSAPrivateKey) -> SigningCertificate:
        certificate = material.self_signed(rsa_key, common_name="ksef2 secret")
        return SigningCertificate(
            XAdESCredentials(certificate, rsa_key), environment=Environment.TEST
        )

    @staticmethod
    def _key_body(key: rsa.RSAPrivateKey) -> str:
        pem = material.key_pem(key).decode()
        body = "".join(
            line for line in pem.splitlines() if not line.startswith("-----")
        )
        return body.replace("\n", "")[40:80]

    def test_no_text_form_shows_the_key(
        self, record: SigningCertificate, rsa_key: rsa.RSAPrivateKey
    ) -> None:
        secret = self._key_body(rsa_key)
        texts = [
            repr(record),
            repr(record.info),
            repr(record.credentials),
            record.info.model_dump_json(),
            str(record),
        ]

        assert secret
        for text in texts:
            assert "PRIVATE KEY" not in text
            assert secret not in text

    def test_the_repr_names_the_reference_and_the_validity_only(
        self, record: SigningCertificate
    ) -> None:
        assert repr(record) == (
            f"SigningCertificate(reference={record.info.reference!r}, "
            f"valid_to={record.info.valid_to.isoformat()})"
        )

    @pytest.mark.parametrize("copier", [pickle.dumps, copy.copy, copy.deepcopy])
    def test_the_pair_refuses_to_be_pickled_or_copied(
        self, record: SigningCertificate, copier: object
    ) -> None:
        with pytest.raises(TypeError, match="cannot be pickled or copied"):
            copier(record)  # type: ignore[operator]

    def test_the_metadata_is_the_part_that_can_be_serialized(
        self, record: SigningCertificate
    ) -> None:
        assert not hasattr(record, "model_dump")
        assert (
            SigningCertificateInfo.model_validate_json(record.info.model_dump_json())
            == record.info
        )
