"""Unit tests for XAdESCredentials, the data-based credentials of with_xades()."""

import base64
import json
from typing import Literal

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed25519, rsa
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import BaseModel, SecretBytes, ValidationError

from ksef2._core.exceptions import KSeFArgumentError
from ksef2._core.xades import build_auth_token_request_xml, sign_xades
from ksef2.models import XAdESCredentials
from ksef2.xades import XAdESCredentials as FacadeXAdESCredentials
from tests.unit.xades_material import (
    CredentialFormat,
    archive,
    build_credentials,
    key_der,
    key_pem,
    public_key_der,
    self_signed,
)

SENTINEL_PASSWORD = b"sentinel-key-password-do-not-keep"
OTHER_SENTINEL_PASSWORD = b"another-sentinel-password-do-not-keep"


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def ec_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture(scope="module")
def other_rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.mark.parametrize("credential_format", ["pem", "der", "pkcs12"])
@pytest.mark.parametrize("key_kind", ["rsa", "ec"], ids=["rsa", "ec"])
@pytest.mark.parametrize("encrypted", [False, True], ids=["plain", "password"])
def test_credentials_support_all_formats(
    credential_format: CredentialFormat,
    key_kind: Literal["rsa", "ec"],
    encrypted: bool,
    rsa_key: rsa.RSAPrivateKey,
    ec_key: ec.EllipticCurvePrivateKey,
) -> None:
    key: PrivateKeyTypes = rsa_key if key_kind == "rsa" else ec_key
    password = SENTINEL_PASSWORD if encrypted else None
    certificate = self_signed(key)

    credentials = build_credentials(
        certificate, key, credential_format, password=password
    )
    signing_cert, signing_key = credentials.to_crypto_material()

    assert signing_cert.public_bytes(Encoding.DER) == certificate.public_bytes(
        Encoding.DER
    )
    assert public_key_der(signing_key) == public_key_der(key)
    assert key_pem(signing_key) == credentials.key_pem.get_secret_value()


@pytest.mark.parametrize("credential_format", ["pem", "der", "pkcs12"])
@pytest.mark.parametrize("key_kind", ["rsa", "ec"], ids=["rsa", "ec"])
def test_resolved_material_signs_a_real_xades_payload(
    credential_format: CredentialFormat,
    key_kind: Literal["rsa", "ec"],
    rsa_key: rsa.RSAPrivateKey,
    ec_key: ec.EllipticCurvePrivateKey,
) -> None:
    """The key the model hands the signer is the one KSeF can verify on the cert."""
    key: PrivateKeyTypes = rsa_key if key_kind == "rsa" else ec_key
    certificate = self_signed(key)
    credentials = build_credentials(certificate, key, credential_format, password=None)

    signing_cert, signing_key = credentials.to_crypto_material()
    signed = sign_xades(
        build_auth_token_request_xml("challenge-value", "1234567890"),
        signing_cert,
        signing_key,
    )

    assert b"SignatureValue" in signed
    assert b"X509Data" in signed
    assert certificate.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo
    ) == public_key_der(signing_key)
    assert signing_cert.fingerprint(hashes.SHA256()) == certificate.fingerprint(
        hashes.SHA256()
    )


def test_encrypted_input_is_decrypted_once_and_nothing_secret_is_kept(
    rsa_key: rsa.RSAPrivateKey,
) -> None:
    """Neither the password nor the ciphertext survives the constructor."""
    certificate = self_signed(rsa_key)
    encrypted_pem = key_pem(rsa_key, password=SENTINEL_PASSWORD)

    credentials = XAdESCredentials.from_pem(
        certificate.public_bytes(Encoding.PEM),
        encrypted_pem,
        key_password=SENTINEL_PASSWORD,
    )

    stored = credentials.key_pem.get_secret_value()
    assert stored != encrypted_pem
    assert SENTINEL_PASSWORD not in stored
    assert b"ENCRYPTED" not in stored
    assert set(type(credentials).model_fields) == {"cert_pem", "key_pem"}


def test_credentials_reject_invalid_material(
    rsa_key: rsa.RSAPrivateKey,
    ec_key: ec.EllipticCurvePrivateKey,
    other_rsa_key: rsa.RSAPrivateKey,
) -> None:
    """Every unreadable or unusable input fails as KSeFArgumentError, before network."""
    certificate = self_signed(rsa_key)
    ec_certificate = self_signed(ec_key)
    ed25519_key = ed25519.Ed25519PrivateKey.generate()
    dsa_key = dsa.generate_private_key(key_size=2048)

    def reject(operation: object, *, from_loader: bool = True) -> KSeFArgumentError:
        with pytest.raises(KSeFArgumentError) as exc_info:
            operation()  # pyright: ignore[reportCallIssue]
        error = exc_info.value
        if from_loader:
            assert isinstance(error.__cause__, (ValueError, TypeError))
        else:
            assert error.__cause__ is None
        return error

    assert "certificate" in str(
        reject(
            lambda: XAdESCredentials.from_pem(
                b"not a certificate at all", key_pem(rsa_key)
            )
        )
    )
    assert "certificate" in str(
        reject(lambda: XAdESCredentials.from_pem(b"", key_pem(rsa_key)))
    )
    assert "certificate" in str(
        reject(lambda: XAdESCredentials.from_pem(key_pem(rsa_key), key_pem(rsa_key)))
    )
    assert "private key" in str(
        reject(
            lambda: XAdESCredentials.from_pem(
                certificate.public_bytes(Encoding.PEM), b"not a private key"
            )
        )
    )
    assert "DER" in str(
        reject(
            lambda: XAdESCredentials.from_der(
                certificate.public_bytes(Encoding.DER)[:120], key_der(rsa_key)
            )
        )
    )
    assert "password" in str(
        reject(
            lambda: XAdESCredentials.from_pem(
                certificate.public_bytes(Encoding.PEM),
                key_pem(rsa_key, password=SENTINEL_PASSWORD),
            )
        )
    )
    assert "password" in str(
        reject(
            lambda: XAdESCredentials.from_pem(
                certificate.public_bytes(Encoding.PEM),
                key_pem(rsa_key),
                key_password=SENTINEL_PASSWORD,
            )
        )
    )
    assert "DER" in str(
        reject(
            lambda: XAdESCredentials.from_der(
                certificate.public_bytes(Encoding.DER),
                key_pem(rsa_key),
            )
        )
    )

    wrong_p12_password = reject(
        lambda: XAdESCredentials.from_pkcs12(
            archive(certificate, rsa_key, password=SENTINEL_PASSWORD),
            password=OTHER_SENTINEL_PASSWORD,
        )
    )
    assert "PKCS#12" in str(wrong_p12_password)
    assert SENTINEL_PASSWORD.decode() not in str(wrong_p12_password.context)

    assert "PKCS#12" in str(
        reject(
            lambda: XAdESCredentials.from_pkcs12(
                archive(certificate, rsa_key, password=SENTINEL_PASSWORD)
            )
        )
    )
    assert "no private key" in str(
        reject(
            lambda: XAdESCredentials.from_pkcs12(archive(certificate, None)),
            from_loader=False,
        )
    )
    assert "no certificate" in str(
        reject(
            lambda: XAdESCredentials.from_pkcs12(archive(None, rsa_key)),
            from_loader=False,
        )
    )
    assert "Ed25519PrivateKey" in str(
        reject(
            lambda: XAdESCredentials.from_pem(
                self_signed(ed25519_key).public_bytes(Encoding.PEM),
                key_pem(ed25519_key),
            ),
            from_loader=False,
        )
    )
    assert "DSAPrivateKey" in str(
        reject(
            lambda: XAdESCredentials.from_pkcs12(
                archive(self_signed(dsa_key), dsa_key)
            ),
            from_loader=False,
        )
    )
    assert "does not belong" in str(
        reject(
            lambda: XAdESCredentials.from_pem(
                certificate.public_bytes(Encoding.PEM), key_pem(other_rsa_key)
            ),
            from_loader=False,
        )
    )
    assert "does not belong" in str(
        reject(
            lambda: XAdESCredentials.from_der(
                ec_certificate.public_bytes(Encoding.DER), key_der(rsa_key)
            ),
            from_loader=False,
        )
    )


def test_mismatched_pair_never_reaches_a_request_for_any_format(
    rsa_key: rsa.RSAPrivateKey, other_rsa_key: rsa.RSAPrivateKey
) -> None:
    """PEM and DER can carry a mismatched pair; a PKCS#12 archive cannot be built."""
    certificate = self_signed(rsa_key)

    with pytest.raises(KSeFArgumentError, match="does not belong"):
        _ = XAdESCredentials.from_pem(
            certificate.public_bytes(Encoding.PEM), key_pem(other_rsa_key)
        )
    with pytest.raises(KSeFArgumentError, match="does not belong"):
        _ = XAdESCredentials.from_der(
            certificate.public_bytes(Encoding.DER), key_der(other_rsa_key)
        )
    with pytest.raises(ValueError, match="do not match"):
        _ = archive(certificate, other_rsa_key)


@pytest.mark.parametrize("credential_format", ["pem", "der", "pkcs12"])
@pytest.mark.parametrize("encrypted", [False, True], ids=["plain", "password"])
def test_rejections_never_carry_secret_material(
    credential_format: CredentialFormat,
    encrypted: bool,
    rsa_key: rsa.RSAPrivateKey,
    other_rsa_key: rsa.RSAPrivateKey,
) -> None:
    """Messages, context and repr of a failure show no key bytes and no password."""
    certificate = self_signed(rsa_key)
    password = SENTINEL_PASSWORD if encrypted else None

    # Every format is fed the same secret inputs together with a key that is not the
    # certificate's. A PKCS#12 archive cannot be built from a mismatched pair, so its
    # archive is correct and is read back with the wrong password instead.
    with pytest.raises(KSeFArgumentError) as exc_info:
        if credential_format == "pkcs12":
            _ = XAdESCredentials.from_pkcs12(
                archive(certificate, rsa_key, password=SENTINEL_PASSWORD),
                password=OTHER_SENTINEL_PASSWORD if encrypted else None,
            )
        else:
            encode = key_pem if credential_format == "pem" else key_der
            to_bytes = (
                certificate.public_bytes(Encoding.PEM)
                if credential_format == "pem"
                else certificate.public_bytes(Encoding.DER)
            )
            wrong_key = encode(
                other_rsa_key, password=SENTINEL_PASSWORD if encrypted else None
            )
            if credential_format == "pem":
                _ = XAdESCredentials.from_pem(
                    to_bytes, wrong_key, key_password=password
                )
            else:
                _ = XAdESCredentials.from_der(
                    to_bytes, wrong_key, key_password=password
                )
    error = exc_info.value

    rendered = " ".join([str(error), repr(error), str(error.context), str(error.args)])
    for secret in (
        SENTINEL_PASSWORD.decode(),
        OTHER_SENTINEL_PASSWORD.decode(),
        key_pem(other_rsa_key, password=SENTINEL_PASSWORD).decode(errors="replace"),
        base64.b64encode(key_pem(other_rsa_key, password=SENTINEL_PASSWORD)).decode(),
    ):
        assert secret not in rendered
    assert error.context["code"] == "ARGUMENT_ERROR"


def test_credentials_redact_private_material(rsa_key: rsa.RSAPrivateKey) -> None:
    """Neither the input key nor the normalized key appears in any generic output."""
    certificate = self_signed(rsa_key)
    original_pem = key_pem(rsa_key, password=SENTINEL_PASSWORD)

    credentials = XAdESCredentials.from_pem(
        certificate.public_bytes(Encoding.PEM),
        original_pem,
        key_password=SENTINEL_PASSWORD,
    )
    normalized_pem = credentials.key_pem.get_secret_value()
    secrets = [
        SENTINEL_PASSWORD.decode(),
        original_pem.decode(),
        normalized_pem.decode(),
        base64.b64encode(normalized_pem).decode(),
    ]
    outputs = [
        repr(credentials),
        str(credentials),
        str(credentials.model_dump()),
        credentials.model_dump_json(),
        str(credentials.model_dump(mode="json")),
        repr(credentials.model_dump()),
    ]
    for output in outputs:
        for secret in secrets:
            assert secret not in output, output[:120]

    class Holder(BaseModel):
        credentials: XAdESCredentials

    holder = Holder(credentials=credentials)
    for output in (
        repr(holder),
        holder.model_dump_json(),
        str(holder.model_dump()),
        str(holder.model_dump(mode="json")),
    ):
        for secret in secrets:
            assert secret not in output, output[:120]

    assert credentials.model_dump() == {"cert_pem": credentials.cert_pem}
    assert holder.model_dump() == {"credentials": {"cert_pem": credentials.cert_pem}}


def test_credentials_schema_and_json_input(rsa_key: rsa.RSAPrivateKey) -> None:
    """The validation schema describes two data fields and JSON input reloads."""
    schema = json.loads(json.dumps(XAdESCredentials.model_json_schema()))

    assert set(schema["properties"]) == {"cert_pem", "key_pem"}
    assert schema["properties"]["key_pem"]["writeOnly"] is True
    assert schema["properties"]["cert_pem"]["type"] == "string"
    assert schema["required"] == ["cert_pem", "key_pem"]

    certificate = self_signed(rsa_key)
    credentials = XAdESCredentials.from_pem(
        certificate.public_bytes(Encoding.PEM), key_pem(rsa_key)
    )
    supplied = json.dumps(
        {
            "cert_pem": credentials.cert_pem.decode(),
            "key_pem": credentials.key_pem.get_secret_value().decode(),
        }
    )

    reloaded = XAdESCredentials.model_validate_json(supplied)
    signing_cert, signing_key = reloaded.to_crypto_material()

    assert signing_cert.public_bytes(Encoding.DER) == certificate.public_bytes(
        Encoding.DER
    )
    assert public_key_der(signing_key) == public_key_der(rsa_key)
    assert "PRIVATE KEY" not in reloaded.model_dump_json()
    assert type(reloaded) is XAdESCredentials is FacadeXAdESCredentials


def test_direct_model_invalid_material_is_rejected(
    rsa_key: rsa.RSAPrivateKey, other_rsa_key: rsa.RSAPrivateKey
) -> None:
    """A model built without a constructor still cannot hand out unusable material."""
    certificate = self_signed(rsa_key)
    mismatched = XAdESCredentials(
        cert_pem=certificate.public_bytes(Encoding.PEM),
        key_pem=SecretBytes(key_pem(other_rsa_key)),
    )
    with pytest.raises(KSeFArgumentError, match="does not belong"):
        _ = mismatched.to_crypto_material()

    with pytest.raises(KSeFArgumentError) as exc_info:
        _ = XAdESCredentials(
            cert_pem=b"junk", key_pem=SecretBytes(b"junk")
        ).to_crypto_material()
    assert "certificate" in str(exc_info.value)
    assert exc_info.value.context["certificate_encoding"] == "pem"

    ed25519_key = ed25519.Ed25519PrivateKey.generate()
    unsupported = XAdESCredentials(
        cert_pem=self_signed(ed25519_key).public_bytes(Encoding.PEM),
        key_pem=SecretBytes(key_pem(ed25519_key)),
    )
    with pytest.raises(KSeFArgumentError, match="Ed25519PrivateKey"):
        _ = unsupported.to_crypto_material()

    sentinel = b"SENTINEL-NOT-LEAK"
    supplied: dict[str, object] = {
        "cert_pem": sentinel,
        "key_pem": {"leak": sentinel.decode()},
    }
    with pytest.raises(ValidationError) as validation_error:
        _ = XAdESCredentials.model_validate(supplied)
    assert sentinel.decode() not in str(validation_error.value)
